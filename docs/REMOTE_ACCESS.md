# Remote access

The native server defaults to localhost. To listen on all IPv4 interfaces, set an API key and use:

```sh
export STRATA_API_KEY='your-private-key'
./Strata.AppImage --host 0.0.0.0 --port 8096
```

A non-local bind is refused without a nonempty API key. Model workers keep their private localhost listeners. The web page can be opened without a key; enter the key in its API-key field to access models, monitoring and controls. API clients must send `Authorization: Bearer <key>`, including clients running on the server itself.

Over Tailscale, open `http://<server-tailscale-ip>:8096/` or use `http://<server-tailscale-ip>:8096/v1` as the API base. Tailscale access rules still apply. Listening on all interfaces also exposes the authenticated service on LAN interfaces; it does not configure firewall rules or internet port forwarding. Use Tailscale or an HTTPS reverse proxy for access over untrusted networks. Cross-origin browser requests remain rejected; ordinary API clients do not need an Origin header.
