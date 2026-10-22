const form = document.querySelector('#download');
const input = document.querySelector('#media-url');
const message = document.querySelector('#form-message');

// Cloudflare Pages serves this same-origin function from functions/api/resolve.js.
const RESOLVER_API = '/api/resolve';
const DIRECT_MEDIA_EXTENSIONS = new Set([
  '3gp', 'aac', 'avi', 'flac', 'm4a', 'm4v', 'mkv', 'mov', 'mp3',
  'mp4', 'mpeg', 'mpg', 'ogg', 'opus', 'wav', 'webm', 'wmv'
]);

function showDirectMediaLink(url) {
  const extension = url.pathname.split('.').pop()?.toLowerCase();
  if (!DIRECT_MEDIA_EXTENSIONS.has(extension)) return false;

  message.replaceChildren();
  const link = document.createElement('a');
  link.href = url.toString();
  link.target = '_blank';
  link.rel = 'noopener';
  link.textContent = `Open direct ${extension.toUpperCase()} download`;
  message.append('Direct media link: ', link);
  return true;
}

function showResult(result) {
  message.replaceChildren();

  if (result.stream_type === 'direct' && result.download_url) {
    const link = document.createElement('a');
    link.href = result.download_url;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = `Download ${result.title || 'media'}.${result.extension || ''}`.replace(/\.$/, '');
    message.append('Ready: ', link);
    return;
  }

  if ((result.stream_type === 'hls' || result.is_hls === true) && result.download_url) {
    message.textContent = 'HLS playlist detected. It needs an HLS-capable player or a server-side FFmpeg pipeline to create a downloadable file. ';
    const link = document.createElement('a');
    link.href = result.download_url;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = 'Open playlist';
    message.append(link);
    return;
  }

  if (result.status === 'redirect' || result.status === 'tunnel') {
    const link = document.createElement('a');
    link.href = result.url;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = result.filename ? `Download ${result.filename}` : 'Download media';
    message.append('Ready: ', link);
    return;
  }

  if (result.status === 'picker' && Array.isArray(result.picker)) {
    message.textContent = 'Multiple files found. Choose one: ';
    result.picker.forEach((item, index) => {
      const link = document.createElement('a');
      link.href = item.url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = `${item.type || 'file'} ${index + 1}`;
      link.style.marginLeft = '8px';
      message.append(link);
    });
    return;
  }

  const code = result.error?.code || 'resolver.failed';
  throw new Error(code);
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const value = input.value.trim();
  message.classList.add('show');

  if (!value) {
    message.textContent = 'Paste a public media URL to get started.';
    input.focus();
    return;
  }

  let resolverStarted = false;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error();

    if (showDirectMediaLink(url)) return;

    message.textContent = 'Analyzing link…';
    resolverStarted = true;
    const response = await fetch(RESOLVER_API, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        url: url.toString(),
        videoQuality: '1080',
        audioFormat: 'mp3',
        filenameStyle: 'pretty'
      })
    });

    const responseText = await response.text();
    let result;
    try {
      result = JSON.parse(responseText);
    } catch {
      const contentType = response.headers.get('content-type') || 'unknown content type';
      if (!response.ok) {
        const diagnostic = responseText.trim().replace(/\s+/g, ' ').slice(0, 240);
        throw new Error(
          `Resolver request failed (HTTP ${response.status}, ${contentType})${
            diagnostic ? `: ${diagnostic}` : '.'
          }`
        );
      }
      throw new Error(`Resolver returned a non-JSON response (HTTP ${response.status}, ${contentType}).`);
    }

    if (!result || typeof result !== 'object') {
      throw new Error('Resolver returned an unexpected JSON response.');
    }

    if (!response.ok) {
      const error = result.error;
      const errorCode = error?.code || (typeof error === 'string' ? error : undefined);
      const details = {
        cobalt_resolver_not_configured: 'Page URLs need a Cobalt resolver. Configure COBALT_API_URL in Cloudflare Pages.',
        yt_dlp_service_not_configured: 'DramaFren links need the yt-dlp service. Configure YTDLP_API_URL in Cloudflare Pages.'
      };
      const detail = details[errorCode] || error?.message || errorCode || result.detail || `resolver.http_${response.status}`;
      throw new Error(detail);
    }
    showResult(result);
  } catch (error) {
    if (resolverStarted) {
      message.textContent = `Resolver error: ${error.message || 'request failed'}`;
    } else {
      message.textContent = 'That does not look like a valid web link yet.';
      input.focus();
    }
  }
});
