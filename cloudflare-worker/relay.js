/**
 * Minimal ntfy.sh relay for GitHub Actions.
 *
 * ntfy.sh blocks GitHub Actions' shared IP ranges (confirmed: every request -
 * GET, POST, even plain curl - gets a 404 from Actions runner IPs). This
 * Worker forwards requests to ntfy.sh from Cloudflare's network instead, so
 * the scheduled workflow can reach it. Everything else about ntfy - the
 * topic, the phone app, the "done <course-id>-<n>" command - stays the same.
 *
 * Deploy via the Cloudflare dashboard (Workers & Pages -> Create -> paste
 * this file -> Deploy), then add a secret binding named RELAY_SECRET (a long
 * random string of your choosing) under Settings -> Variables. Give the
 * resulting *.workers.dev URL and that same secret to the tracker repo as
 * the NTFY_RELAY_URL / NTFY_RELAY_SECRET Actions secrets.
 */
export default {
  async fetch(request, env) {
    if (request.headers.get("X-Relay-Secret") !== env.RELAY_SECRET) {
      return new Response("Forbidden", { status: 403 });
    }

    const url = new URL(request.url);
    const target = "https://ntfy.sh" + url.pathname + url.search;

    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.delete("x-relay-secret");

    const init = {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    };

    const upstream = await fetch(target, init);
    const responseHeaders = new Headers(upstream.headers);
    responseHeaders.delete("content-encoding");
    responseHeaders.delete("content-length");
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  },
};
