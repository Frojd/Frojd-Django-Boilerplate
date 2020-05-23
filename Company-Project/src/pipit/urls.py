from django.contrib import admin
from django.conf import settings
from django.conf.urls import url, include
from django.conf.urls.static import static
from django.views import defaults as default_views
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls
from wagtail.core import urls as wagtail_urls
from wagtail.contrib.sitemaps.views import sitemap

from main.views.page_not_found import PageNotFoundView
from main.views.error_500 import error_500_view


handler404 = PageNotFoundView.as_view()
handler500 = error_500_view

urlpatterns = []

if settings.DEBUG:
    urlpatterns += [
        url(
            r"^400/$",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),  # NOQA
        url(
            r"^403/$",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),  # NOQA
        url(
            r"^404/$", handler404, kwargs={"exception": Exception("Page not Found")}
        ),  # NOQA
        url(
            r"^500/$", handler500, kwargs={"exception": Exception("Internal error")}
        ),  # NOQA
    ]

    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns += [url(r"^__debug__/", include(debug_toolbar.urls))]

    if "revproxy" in settings.INSTALLED_APPS:
        from revproxy.views import ProxyView
        from urllib3 import PoolManager

        CustomProxyView = ProxyView

        if settings.REACT_DEVSERVER_URL.startswith("https://"):
            class NoSSLVerifyProxyView(ProxyView):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.http = PoolManager(
                        cert_reqs='CERT_NONE', assert_hostname=False
                    )

            CustomProxyView = NoSSLVerifyProxyView

        urlpatterns += [
            url(r'^proxy/(?P<path>.*)$',
                CustomProxyView.as_view(upstream=settings.REACT_DEVSERVER_URL)
            ),
        ]

urlpatterns += [
    url(settings.ADMIN_URL, admin.site.urls),
    url(r"^cms/", include(wagtailadmin_urls)),
    url(r"^documents/", include(wagtaildocs_urls)),
    url("^sitemap\.xml$", sitemap, name="sitemap"),
]

urlpatterns += [url(r"", include(wagtail_urls))]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
