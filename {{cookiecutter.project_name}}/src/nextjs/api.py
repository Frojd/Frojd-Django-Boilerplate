from django.contrib.contenttypes.models import ContentType
from django.http import Http404
from django.middleware import csrf as csrf_middleware
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.module_loading import import_string
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from wagtail.api.v2.router import WagtailAPIRouter
from wagtail.api.v2.views import PagesAPIViewSet, BaseAPIViewSet
from wagtail.core.forms import PasswordViewRestrictionForm
from wagtail.core.models import Page, Site, PageViewRestriction
from wagtail.core.wagtail_hooks import require_wagtail_login
from wagtail.contrib.redirects.models import Redirect
from wagtail.contrib.redirects.middleware import get_redirect
from wagtail_headless_preview.models import PagePreview


api_router = WagtailAPIRouter("nextjs")


class PageRelativeUrlListSerializer(serializers.Serializer):
    def to_representation(self, obj):
        return {
            "title": obj.title,
            "relative_url": obj.get_url(None),
        }


class PageRelativeUrlListAPIViewSet(PagesAPIViewSet):
    """Return all pages and their relative url"""

    def get_serializer(self, qs, many=True):
        return PageRelativeUrlListSerializer(qs, many=many)

    @classmethod
    def get_urlpatterns(cls):
        return [
            path("", cls.as_view({"get": "listing_view"}), name="listing"),
        ]


api_router.register_endpoint("page_relative_urls", PageRelativeUrlListAPIViewSet)


class PagePreviewAPIViewSet(BaseAPIViewSet):
    known_query_parameters = PagesAPIViewSet.known_query_parameters.union(
        ["content_type", "token"]
    )

    def listing_view(self, request):
        page = self.get_object()
        data = page.get_component_data(
            {
                "request": request,
            }
        )
        return Response(data)

    def get_object(self):
        content_type = self.request.GET.get("content_type")
        if not content_type:
            raise ValidationError("Missing content_type")

        app_label, model = content_type.split(".")
        content_type = ContentType.objects.get(app_label=app_label, model=model)

        token = self.request.GET.get("token")
        if not token:
            raise ValidationError("Missing token")

        page_preview = PagePreview.objects.get(
            content_type=content_type,
            token=token,
        )
        page = page_preview.as_page()
        if not page.pk:
            # fake primary key to stop API URL routing from complaining
            page.pk = 0

        return page

    @classmethod
    def get_urlpatterns(cls):
        return [
            path("", cls.as_view({"get": "listing_view"}), name="listing"),
        ]


api_router.register_endpoint("page_preview", PagePreviewAPIViewSet)


class PasswordProtectedPageViewSet(BaseAPIViewSet):
    known_query_parameters = BaseAPIViewSet.known_query_parameters.union(
        ["restriction_id", "page_id"]
    )

    def detail_view(self, request, page_view_restriction_id=None, page_id=None):
        restriction = get_object_or_404(
            PageViewRestriction, id=page_view_restriction_id
        )
        page = get_object_or_404(Page, id=page_id).specific

        post = request.data.copy()
        post["return_url"] = "/required_for_validation"

        form = PasswordViewRestrictionForm(post, instance=restriction)
        if not form.is_valid():
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        data = page.get_component_data(
            {
                "request": request,
            }
        )
        return Response(data)

    @classmethod
    def get_urlpatterns(cls):
        return [
            path(
                "<int:page_view_restriction_id>/<int:page_id>/",
                cls.as_view({"post": "detail_view"}),
                name="detail_view",
            ),
        ]


api_router.register_endpoint("password_protected_page", PasswordProtectedPageViewSet)


class PageByPathAPIViewSet(BaseAPIViewSet):
    known_query_parameters = BaseAPIViewSet.known_query_parameters.union(["html_path"])

    def listing_view(self, request):
        page, args, kwargs = self.get_object()

        for restriction in page.get_view_restrictions():
            if not restriction.accept_request(request):
                if restriction.restriction_type == PageViewRestriction.PASSWORD:
                    data = {
                        "component_name": "PasswordProtectedPage",
                        "component_props": {
                            "restriction_id": restriction.id,
                            "page_id": page.id,
                            "csrf_token": csrf_middleware.get_token(request),
                        },
                    }
                    return Response(data)

                elif restriction.restriction_type in [
                    PageViewRestriction.LOGIN,
                    PageViewRestriction.GROUPS,
                ]:
                    site = Site.find_for_request(self.request)
                    resp = require_wagtail_login(next=page.relative_url(site, request))
                    data = {
                        "component_name": "RedirectPage",
                        "component_props": {
                            "redirect_url": resp.url,
                        },
                    }
                    return Response(data)

        return page.serve(request, *args, **kwargs)

    def get_object(self):
        path = self.request.GET.get("html_path", None)
        if path is None:
            raise ValidationError("Missing html_path")

        site = Site.find_for_request(self.request)
        if not site:
            raise Http404

        path_components = [component for component in path.split('/') if component]
        page, args, kwargs = site.root_page.specific.route(self.request, path_components)
        return page, args, kwargs

    @classmethod
    def get_urlpatterns(cls):
        return [
            path("", cls.as_view({"get": "listing_view"}), name="listing"),
        ]


api_router.register_endpoint("page_by_path", PageByPathAPIViewSet)


class ExternalViewDataAPIViewSet(BaseAPIViewSet):
    view_register = {
        "404": "main.views.page_not_found.PageNotFoundView",
    }

    def detail_view(self, request, pk):
        try:
            view_cls = self.view_register[pk]
        except:
            raise Http404
        if isinstance(view_cls, str):
            view_cls = import_string(view_cls)

        view = view_cls.as_view()
        resp = view(request)
        resp.status_code = 200
        return resp

    @classmethod
    def get_urlpatterns(cls):
        return [
            path("<str:pk>/", cls.as_view({"get": "detail_view"}), name="detail"),
        ]


api_router.register_endpoint("external_view_data", ExternalViewDataAPIViewSet)


class RedirectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Redirect
        fields = ["old_path", "link", "is_permanent"]


class RedirectByPathAPIViewSet(BaseAPIViewSet):
    known_query_parameters = BaseAPIViewSet.known_query_parameters.union(["html_path"])

    def detail_view(self, request):
        redirect = self.get_object()
        serializer = self.get_serializer(redirect, many=False)
        return Response(serializer.data)

    def get_object(self):
        path = self.request.GET.get("html_path", None)
        if path == None:
            raise ValidationError("Missing html_path")

        site = Site.find_for_request(self.request)
        path = Redirect.normalise_path(path)

        redirect = get_redirect(self.request, path)
        if not redirect:
            raise Http404
        return redirect

    def get_serializer(self, qs, many=True):
        return RedirectSerializer(qs, many=many)

    @classmethod
    def get_urlpatterns(cls):
        return [
            path("", cls.as_view({"get": "detail_view"}), name="detail"),
        ]


api_router.register_endpoint("redirect_by_path", RedirectByPathAPIViewSet)