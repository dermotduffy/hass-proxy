"""HASS Proxy proxy."""

from __future__ import annotations

import time
import urllib
import uuid
from typing import TYPE_CHECKING, Any

import urlmatch
import voluptuous as vol
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_loaded_integration
from homeassistant.util.ssl import (
    SSLCipherList,
    client_context,
    client_context_no_verify,
)

from custom_components.hass_proxy.const import DOMAIN
from custom_components.hass_proxy.data import (
    DynamicProxiedURL,
    HASSProxyConfigEntry,
    HASSProxyData,
)
from custom_components.hass_proxy.proxy_lib import (
    HASSProxyLibExpiredError,
    HASSProxyLibNotFoundRequestError,
    ProxiedURL,
    ProxyView,
)

from .const import (
    CONF_DYNAMIC_URLS,
    CONF_SSL_CIPHERS,
    CONF_SSL_CIPHERS_DEFAULT,
    CONF_SSL_CIPHERS_INSECURE,
    CONF_SSL_CIPHERS_INTERMEDIATE,
    CONF_SSL_CIPHERS_MODERN,
    CONF_SSL_VERIFICATION,
    SERVICE_CREATE_PROXIED_URL,
    SERVICE_DELETE_PROXIED_URL,
)

if TYPE_CHECKING:
    import ssl
    from types import MappingProxyType

    import aiohttp
    from aiohttp import web
    from homeassistant.core import HomeAssistant, ServiceCall

    from .const import HASSProxySSLCiphers

CREATE_PROXIED_URL_SCHEMA = vol.Schema(
    {
        vol.Required("url_pattern"): cv.string,
        vol.Optional("url_id"): cv.string,
        vol.Optional("ssl_verification", default=True): cv.boolean,
        vol.Optional("ssl_ciphers", default=CONF_SSL_CIPHERS_DEFAULT): vol.Any(
            None,
            CONF_SSL_CIPHERS_INSECURE,
            CONF_SSL_CIPHERS_MODERN,
            CONF_SSL_CIPHERS_INTERMEDIATE,
            CONF_SSL_CIPHERS_DEFAULT,
        ),
        vol.Optional("open_limit", default=1): cv.positive_int,
        vol.Optional("time_to_live", default=60): cv.positive_int,
    },
    required=True,
)

DELETE_PROXIED_URL_SCHEMA = vol.Schema(
    {
        vol.Required("url_id"): cv.string,
    },
    required=True,
)


class HASSProxyError(Exception):
    """Exception to indicate a general Proxy error."""


class HASSProxyURLIDNotFoundError(HASSProxyError):
    """Exception to indicate that a URL ID was not found."""


@callback
async def async_setup_entry(hass: HomeAssistant, entry: HASSProxyConfigEntry) -> None:
    """Set up the proxy entry."""
    session = async_get_clientsession(hass)
    hass.http.register_view(V0ProxyView(hass, session))

    entry.runtime_data = HASSProxyData(
        integration=async_get_loaded_integration(hass, entry.domain),
        dynamic_proxied_urls={},
    )

    def create_proxied_url(call: ServiceCall) -> None:
        """Create a proxied URL."""
        url_id = call.data.get("url_id") or str(uuid.uuid4())
        ttl = call.data["time_to_live"]

        entry.runtime_data.dynamic_proxied_urls[url_id] = DynamicProxiedURL(
            url_pattern=call.data["url_pattern"],
            ssl_verification=call.data["ssl_verification"],
            ssl_ciphers=call.data["ssl_ciphers"],
            open_limit=call.data["open_limit"],
            expiration=time.time() + ttl if ttl else 0,
        )

    def delete_proxied_url(call: ServiceCall) -> None:
        """Delete a proxied URL."""
        url_id = call.data["url_id"]
        dynamic_proxied_urls = entry.runtime_data.dynamic_proxied_urls

        if url_id not in dynamic_proxied_urls:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="url_id_not_found",
                translation_placeholders={"url_id": url_id},
            )
        del entry.runtime_data.dynamic_proxied_urls[url_id]

    if entry.options.get(CONF_DYNAMIC_URLS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CREATE_PROXIED_URL,
            create_proxied_url,
            CREATE_PROXIED_URL_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_DELETE_PROXIED_URL,
            delete_proxied_url,
            DELETE_PROXIED_URL_SCHEMA,
        )


@callback
async def async_unload_entry(hass: HomeAssistant, entry: HASSProxyConfigEntry) -> None:
    """Unload the proxy entry."""
    if entry.options.get(CONF_DYNAMIC_URLS):
        hass.services.async_remove(DOMAIN, SERVICE_CREATE_PROXIED_URL)
        hass.services.async_remove(DOMAIN, SERVICE_DELETE_PROXIED_URL)


class HAProxyView(ProxyView):
    """A proxy view for HomeAssistant."""

    def __init__(self, hass: HomeAssistant, websession: aiohttp.ClientSession) -> None:
        """Initialize the HASS Proxy view."""
        self._hass = hass
        super().__init__(websession)

    def _get_config_entry(self) -> HASSProxyConfigEntry:
        """Get the config entry."""
        return self._hass.config_entries.async_entries(DOMAIN)[0]

    def get_dynamic_proxied_urls(self) -> dict[str, DynamicProxiedURL]:
        """Get the dynamic proxied URLs."""
        return self._get_config_entry().runtime_data.dynamic_proxied_urls

    def _get_options(self) -> MappingProxyType[str, Any]:
        """Get a ConfigEntry options for a given request."""
        return self._get_config_entry().options

    def _get_proxied_url(self, request: web.Request) -> ProxiedURL:
        """Get the URL to proxy."""
        if "url" not in request.query:
            raise HASSProxyLibNotFoundRequestError

        options = self._get_options()
        url_to_proxy = urllib.parse.unquote(request.query["url"])
        has_expired_match = False

        proxied_urls = self.get_dynamic_proxied_urls()
        for [url_id, proxied_url] in proxied_urls.items():
            if urlmatch.urlmatch(
                proxied_url.url_pattern,
                url_to_proxy,
                path_required=False,
            ):
                if proxied_url.expiration and proxied_url.expiration < time.time():
                    has_expired_match = True
                    continue

                if proxied_url.open_limit:
                    proxied_url.open_limit -= 1
                    if proxied_url.open_limit == 0:
                        del proxied_urls[url_id]

                return ProxiedURL(
                    url=url_to_proxy,
                    ssl_context=self._get_ssl_context(proxied_url.ssl_ciphers)
                    if proxied_url.ssl_verification
                    else self._get_ssl_context_no_verify(proxied_url.ssl_ciphers),
                )

        for url_pattern in self._get_options().get("url_patterns", []):
            if urlmatch.urlmatch(url_pattern, url_to_proxy, path_required=False):
                ssl_cipher = options.get(CONF_SSL_CIPHERS)
                ssl_verification = options.get(CONF_SSL_VERIFICATION, True)

                return ProxiedURL(
                    url=url_to_proxy,
                    ssl_context=self._get_ssl_context(ssl_cipher)
                    if ssl_verification
                    else self._get_ssl_context_no_verify(ssl_cipher),
                )

        if has_expired_match:
            raise HASSProxyLibExpiredError
        raise HASSProxyLibNotFoundRequestError

    def _get_ssl_context_no_verify(
        self, ssl_cipher: HASSProxySSLCiphers
    ) -> ssl.SSLContext:
        """Get an SSL context."""
        return client_context_no_verify(
            self._proxy_ssl_cipher_to_ha_ssl_cipher(ssl_cipher)
        )

    def _get_ssl_context(self, ssl_ciphers: HASSProxySSLCiphers) -> ssl.SSLContext:
        """Get an SSL context."""
        return client_context(self._proxy_ssl_cipher_to_ha_ssl_cipher(ssl_ciphers))

    def _proxy_ssl_cipher_to_ha_ssl_cipher(self, ssl_ciphers: str) -> SSLCipherList:
        """Convert a proxy SSL cipher to a HA SSL cipher."""
        if ssl_ciphers == CONF_SSL_CIPHERS_DEFAULT:
            return SSLCipherList.PYTHON_DEFAULT
        return ssl_ciphers


class V0ProxyView(HAProxyView):
    """A v0 proxy endpoint."""

    url = "/api/hass_proxy/v0/"
    name = "api:hass_proxy:v0"
