# `hass-web-proxy-integration`

A small [Home Assistant](https://www.home-assistant.io/) integration to
optionally proxy select web traffic through a Home Assistant instance.

## Why?

Typical usecases are Lovelace cards (e.g. [Frigate
Card](https://github.com/dermotduffy/frigate-hass-card)) that cannot directly
access resources required (either because the browser may not be on the same
network as the backend resources, or because the browser may not allow [Mixed
Content](https://developer.mozilla.org/en-US/docs/Web/Security/Mixed_content)).

## How can this integration help?

There are two main styles of proxying:

- Statically proxying a set of URL patterns (e.g. Accessing `https://$HA_INSTANCE/api/hass_web_proxy/v0/?url=http%3A%2F%2Fcam-back-yard.mydomain.io` will result in a request to `http://cam-back-yard.mydomain.io`).
- Accept Home Assistant `action` calls to selectively allow proxying, for use in automations or `hass-web-proxy-integration` aware Lovelace cards that dynamically select what to proxy.

## Installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dermotduffy&repository=hass-web-proxy-integration&category=integration)

Download the integration via HACS as normal:

- Click `+ EXPLORE & DOWNLOAD REPOSITORIES`
- Search for `Home Assistant Web Proxy`
- Click `DOWNLOAD`

Install the integration to your Home Assistant instance:

- Navigate `Settings -> Devices & Services`
- Click `+ Add INTEGRATION`
- Search and install `Home Assistant Web Proxy`
- Click `FINISH`

## Basic Usage

The integration does not proxy anything by default. There are two methods to actually
proxy:

### Set up static URL Proxying

With this method, the user manually configures static URL patterns to allow proxying for.

Visit the options configuration for the integration:

- Navigate `Settings -> Devices & Services`
- Click through `Home Assistant Web Proxy` in the list of installed integrations
- Click `CONFIGURE`
- Click `+ ADD` to add a URL pattern that should be allowed proxy through the integration
  (e.g. `https://cam-*.mydomain.io` to allow proxying any hostname that starts with
  `cam-` in the `mydomain.io` domain)
- Click `SUBMIT`

Result:

- If the example target to proxy is `http://cam-back-yard.mydomain.io`, first URL encode
  it to `http%3A%2F%2Fcam-back-yard.mydomain.io`
- Visiting
  `https://$HA_INSTANCE/api/hass_web_proxy/v0/?url=http%3A%2F%2Fcam-back-yard.mydomain.io`
  will proxy through Home Assistant for authenticated Home Assistant users.

### Create a dynamic URL proxy

With this method, the user, Home Assistant automation or Lovelace cards, can dynamically
request a URL be proxied:

- Call the `hass_web_proxy.create_proxied_url` action:

```yaml
action: hass_web_proxy.create_proxied_url
data:
  url_pattern: https://cam-*.mydomain.io
  url_id: id-that-can-optionally-be-used-to-delete-later
```

Result:

- If the example target to proxy is `http://cam-back-yard.mydomain.io`, first URL encode
  it to `http%3A%2F%2Fcam-back-yard.mydomain.io`
- Visiting
  `https://$HA_INSTANCE/api/hass_web_proxy/v0/?url=http%3A%2F%2Fcam-back-yard.mydomain.io`
  will proxy through Home Assistant for authenticated Home Assistant users.
- The service call will return a dictionary with a `url_id` parameter referring
  to the created proxied URL.

To delete the proxied URL:

- Call the `hass_web_proxy.delete_proxied_url` action:

```yaml
action: hass_web_proxy.delete_proxied_url
data:
  url_id: id-that-can-optionally-be-used-to-delete-later
```

## Reference

### Configuration Options

| Name               | Default   | Description                                                                                                                                                                    |
| ------------------ | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `dynamic_urls`     | `true`    | Whether to allow to creation and deletion of dynamic proxy URL targets via the `hass_web_proxy.create_proxied_url` and `hass_web_proxy.delete_proxied_url` calls respectively. |
| `ssl_verification` | `true`    | Whether SSL certifications/hostnames should be verified on the proxy URL targets.                                                                                              |
| `ssl_ciphers`      | `default` | Whether to use `default`, `modern`, `intermediate`, or `insecure` ciphers. Older devices may not support default or modern ciphers.                                            |
| `url_patterns`     | `[]`      | An optional list of static [URL patterns](https://github.com/jessepollak/urlmatch) to allow proxying for, e.g. `[ http://cam-*.mydomain.io ]`                                  |

### Dynamic Service Options

#### `hass_web_proxy.create_proxied_url`

```yaml
action: hass_web_proxy.create_proxied_url
data: [...]
```

| Name                    | Default   | Description                                                                                                                                                                                                  |
| ----------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `open_limit`            |           | An optional number of times a URL pattern may be proxied to before it is automatically removed as a proxied URL.                                                                                             |
| `ssl_verification`      | `true`    | Whether SSL certifications/hostnames should be verified on the proxy URL targets.                                                                                                                            |
| `ssl_ciphers`           | `default` | Whether to use `default`, `modern`, `intermediate`, or `insecure` ciphers. Older devices may not support default or modern ciphers.                                                                          |
| `ttl`                   |           | An optional number of seconds to allow proxying of this URL pattern.                                                                                                                                         |
| `url_pattern`           |           | An required [URL pattern](https://github.com/jessepollak/urlmatch) to allow proxying for, e.g. `http://cam-*.mydomain.io`.                                                                                   |
| `url_id`                | [UUID]    | An optional ID that can be used to refer to that proxied URL later (e.g. to delete it with the `hass_web_proxy.delete_proxied_url` action). A UUID is automatically used if this parameter is not specified. |
| `allow_unauthenticated` | `false`   | If `false`, or unset, unauthenticated HA users will not be allowed to access the proxied URL. If `true`, they will. See below.                                                                               |

#### `hass_web_proxy.delete_proxied_url`

```yaml
action: hass_web_proxy.delete_proxied_url
data: [...]
```

| Name     | Default | Description                                                                                                       |
| -------- | ------- | ----------------------------------------------------------------------------------------------------------------- |
| `url_id` |         | An id of a URL pattern to delete, that was previously created using the `hass_web_proxy.create_proxied_url` call. |

## Considerations

### Security

No URLs are proxied by default.

However, any user, automation or Javascript with authenticated access to the
Home Assistant instance could call `hass_web_proxy.create_proxied_url` to create
a dynamically proxied URL, thus exposing arbitrary resources "behind" Home
Assistant to anything/anyone that can access Home Assistant itself.
Depending on the setup, this may present an access escalation beyond what would
usually be accessible. In particular, wide exposure could occur if the user,
automation or Javascript set `allow_unauthenticated` in the dynamically proxied
URL request, which would allow arbitrary internet traffic to be proxied via the
Home Assistant instance regardless of whether or not they have valid user
credentials on the HA instance.

### Performance

All proxying is done by the integration which runs as part of the Home Assistant
process itself. As such, this proxy is not expected to be particularly
performant and excessive usage could slow Home Assistant itself down. This is
unlikely to be noticeable in practice for casual usage.

