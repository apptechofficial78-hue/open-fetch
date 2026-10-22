function isDramaFren(url) {
  return url.hostname === 'dramafren.org' || url.hostname.endsWith('.dramafren.org');
}

export async function onRequestPost({ request, env }) {
  let body;

  try {
    body = await request.json();
  } catch {
    return Response.json({ error: 'invalid_json' }, { status: 400 });
  }

  let mediaUrl;
  try {
    mediaUrl = new URL(body?.url);
  } catch {
    return Response.json({ error: 'invalid_url' }, { status: 400 });
  }

  if (!['http:', 'https:'].includes(mediaUrl.protocol)) {
    return Response.json({ error: 'unsupported_protocol' }, { status: 400 });
  }

  if (isDramaFren(mediaUrl)) {
    if (!env?.YTDLP_API_URL) {
      return Response.json({ error: 'yt_dlp_service_not_configured' }, { status: 503 });
    }

    const ytDlpResponse = await fetch(`${env.YTDLP_API_URL.replace(/\/$/, '')}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: mediaUrl.toString() })
    });

    return new Response(await ytDlpResponse.text(), {
      status: ytDlpResponse.status,
      headers: { 'Content-Type': ytDlpResponse.headers.get('Content-Type') || 'application/json' }
    });
  }

  if (!env?.COBALT_API_URL) {
    return Response.json({ error: 'cobalt_resolver_not_configured' }, { status: 503 });
  }

  let cobaltApiUrl;
  try {
    cobaltApiUrl = new URL(env.COBALT_API_URL);
  } catch {
    return Response.json({ error: 'invalid_cobalt_resolver_url' }, { status: 500 });
  }

  if (!['http:', 'https:'].includes(cobaltApiUrl.protocol)) {
    return Response.json({ error: 'invalid_cobalt_resolver_url' }, { status: 500 });
  }

  const resolverResponse = await fetch(cobaltApiUrl, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      url: mediaUrl.toString(),
      videoQuality: '1080',
      audioFormat: 'mp3',
      filenameStyle: 'pretty'
    })
  });

  const responseBody = await resolverResponse.text();
  return new Response(responseBody, {
    status: resolverResponse.status,
    headers: { 'Content-Type': resolverResponse.headers.get('Content-Type') || 'application/json' }
  });
}

export async function onRequest() {
  return Response.json({ error: 'method_not_allowed' }, { status: 405 });
}
