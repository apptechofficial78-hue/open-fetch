function isDramaFren(url) {
  return url.hostname === 'dramafren.org' || url.hostname.endsWith('.dramafren.org');
}

async function proxyPython(url, mode, audioFormat, env) {
  if (!env?.YTDLP_API_URL) {
    return Response.json({ error: { code: 'yt_dlp_service_not_configured', message: 'The Python extraction fallback is not configured.' } }, { status: 503 });
  }

  const response = await fetch(`${env.YTDLP_API_URL.replace(/\/$/, '')}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: url.toString(), downloadMode: mode, audioFormat })
  });
  const responseText = await response.text();
  let payload;
  try { payload = JSON.parse(responseText); } catch { payload = null; }

  if (mode === 'audio' && response.ok && payload && typeof payload === 'object') {
    const sourceUrl = payload.download_url || payload.url;
    if (sourceUrl) {
      payload.download_url = `${env.YTDLP_API_URL.replace(/\/$/, '')}/download?url=${encodeURIComponent(sourceUrl)}&format=${encodeURIComponent(audioFormat)}`;
      payload.url = payload.download_url;
      payload.extension = audioFormat;
      payload.filename = payload.title ? `${payload.title}.${audioFormat}` : `openfetch.${audioFormat}`;
    }
  }

  return Response.json(payload || { error: { code: 'fallback_error', message: responseText || 'The fallback service returned an invalid response.' } }, { status: response.status });
}

export async function onRequestPost({ request, env }) {
  let body;
  try { body = await request.json(); } catch {
    return Response.json({ error: { code: 'invalid_json', message: 'The request body must be JSON.' } }, { status: 400 });
  }

  let mediaUrl;
  try { mediaUrl = new URL(body?.url); } catch {
    return Response.json({ error: { code: 'invalid_url', message: 'Enter a valid public HTTP or HTTPS URL.' } }, { status: 400 });
  }
  if (!['http:', 'https:'].includes(mediaUrl.protocol)) {
    return Response.json({ error: { code: 'unsupported_protocol', message: 'Only HTTP and HTTPS URLs are supported.' } }, { status: 400 });
  }

  const mode = ['video', 'audio'].includes(body.downloadMode) ? body.downloadMode : 'video';
  const audioFormat = ['mp3', 'm4a', 'opus', 'wav'].includes(body.audioFormat) ? body.audioFormat : 'mp3';

  if (isDramaFren(mediaUrl)) return proxyPython(mediaUrl, mode, audioFormat, env);

  let cobaltApiUrl;
  try { cobaltApiUrl = new URL(env?.COBALT_API_URL || 'https://api.cobalt.tools'); } catch {
    return Response.json({ error: { code: 'invalid_cobalt_resolver_url', message: 'The Cobalt resolver URL is invalid.' } }, { status: 500 });
  }

  const headers = { Accept: 'application/json', 'Content-Type': 'application/json' };
  if (env?.COBALT_API_TOKEN) headers.Authorization = `Bearer ${env.COBALT_API_TOKEN}`;

  try {
    const resolverResponse = await fetch(cobaltApiUrl, {
      method: 'POST', headers,
      body: JSON.stringify({
        url: mediaUrl.toString(),
        videoQuality: mode === 'audio' ? 'audioOnly' : '1080',
        downloadMode: mode,
        audioFormat,
        filenameStyle: 'pretty'
      })
    });
    const responseText = await resolverResponse.text();
    if (resolverResponse.ok) {
      return new Response(responseText, { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
  } catch {}

  return proxyPython(mediaUrl, mode, audioFormat, env);
}

export async function onRequest() {
  return Response.json({ error: { code: 'method_not_allowed', message: 'Use POST to resolve a media URL.' } }, { status: 405 });
}
