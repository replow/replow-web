import type { ChapterText, ShelfBook } from './types';

const escapeXml = (value: string) =>
  value
    // biome-ignore lint/suspicious/noControlCharactersInRegex: Strip forbidden XML control characters from book text.
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '')
    .replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[c] ?? c);
const xhtml = (title: string, body: string) =>
  '<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN"><head><title>' +
  escapeXml(title) +
  '</title><meta charset="utf-8"/></head><body>' +
  body +
  '</body></html>';

export async function packageEpub(book: ShelfBook, chapters: ChapterText[]) {
  const { default: JSZip } = await import('jszip');
  const zip = new JSZip();
  zip.file('mimetype', 'application/epub+zip', { compression: 'STORE' });
  zip.file(
    'META-INF/container.xml',
    '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
  );
  const manifest: string[] = [],
    spine: string[] = [],
    navigation: string[] = [];
  for (const [index, chapter] of chapters.entries()) {
    const name = `c${index}.xhtml`;
    zip.file(
      `EPUB/${name}`,
      xhtml(
        chapter.title,
        '<h1>' +
          escapeXml(chapter.title) +
          '</h1>' +
          chapter.text
            .split('\n')
            .filter((x) => x.trim())
            .map((x) => `<p>${escapeXml(x)}</p>`)
            .join(''),
      ),
    );
    manifest.push(`<item id="c${index}" href="${name}" media-type="application/xhtml+xml"/>`);
    spine.push(`<itemref idref="c${index}"/>`);
    navigation.push(`<li><a href="${name}">${escapeXml(chapter.title)}</a></li>`);
  }
  zip.file('EPUB/nav.xhtml', xhtml('目录', `<nav epub:type="toc"><h1>目录</h1><ol>${navigation.join('')}</ol></nav>`));
  zip.file(
    'EPUB/package.opf',
    '<?xml version="1.0"?><package version="3.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">miro:' +
      escapeXml(book.source_id) +
      '</dc:identifier><dc:title>' +
      escapeXml(book.title) +
      '</dc:title><dc:creator>' +
      escapeXml(book.author) +
      '</dc:creator><dc:language>zh-CN</dc:language><meta property="dcterms:modified">' +
      new Date().toISOString().replace(/\.\d+Z$/, 'Z') +
      '</meta></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>' +
      manifest.join('') +
      '</manifest><spine>' +
      spine.join('') +
      '</spine></package>',
  );
  return zip.generateAsync({
    type: 'blob',
    mimeType: 'application/epub+zip',
    compression: 'DEFLATE',
    compressionOptions: { level: 3 },
  });
}
export async function inspectEpub(blob: Blob) {
  if (blob.size > 150 * 1024 * 1024) throw new Error('请选择小于 150 MB 的 EPUB。');
  let buffer = await blob.arrayBuffer();
  const { default: JSZip } = await import('jszip');
  const zip = await JSZip.loadAsync(buffer);
  if (!zip.file('META-INF/container.xml') || Object.keys(zip.files).length > 10000)
    throw new Error('这不是有效的 EPUB 文件，或书籍过大。');
  const parser = new DOMParser();
  const containerFile = zip.file('META-INF/container.xml');
  if (!containerFile) throw new Error('EPUB 缺少容器信息。');
  const container = parser.parseFromString(await containerFile.async('string'), 'application/xml');
  const opfPath = container.getElementsByTagName('rootfile')[0]?.getAttribute('full-path') || '';
  const opf = zip.file(opfPath);
  if (!opf || opfPath.startsWith('/') || opfPath.split('/').includes('..')) throw new Error('EPUB 缺少有效的书籍信息。');
  const document = parser.parseFromString(await opf.async('string'), 'application/xml');
  if (document.querySelector('parsererror') || !document.getElementsByTagName('spine').length)
    throw new Error('EPUB 结构无效，请选择完整的书籍文件。');
  const title =
    document.getElementsByTagNameNS('http://purl.org/dc/elements/1.1/', 'title')[0]?.textContent?.trim() || '未命名书籍';
  const author =
    document.getElementsByTagNameNS('http://purl.org/dc/elements/1.1/', 'creator')[0]?.textContent?.trim() || '作者未知';
  const manifest = new Map(Array.from(document.getElementsByTagName('item')).map((entry) => [entry.getAttribute('id'), entry]));
  const directory = opfPath.slice(0, opfPath.lastIndexOf('/') + 1);
  const resolveEntry = (href: string) => {
    const url = new URL(href.split('#')[0], `https://epub.invalid/${directory}`);
    return url.origin === 'https://epub.invalid' ? decodeURIComponent(url.pathname.slice(1)) : '';
  };
  const spineEntries = Array.from(document.getElementsByTagName('itemref'));
  if (!spineEntries.length) throw new Error('EPUB 没有可阅读的章节，请重新导入完整书籍。');
  for (const entry of spineEntries) {
    const href = manifest.get(entry.getAttribute('idref'))?.getAttribute('href');
    if (!href || !zip.file(resolveEntry(href))) throw new Error('EPUB 缺少章节文件，请重新导入完整书籍；本机副本已保留。');
  }
  // epub.js leaves book.ready pending when a declared navigation file cannot be read.
  // Drop only the broken optional navigation reference in the in-memory copy.
  let repaired = false;
  for (const entry of manifest.values()) {
    const properties = entry.getAttribute('properties')?.split(/\s+/) || [];
    const isNav = properties.includes('nav');
    const isNcx = entry.getAttribute('media-type') === 'application/x-dtbncx+xml';
    if (!isNav && !isNcx) continue;
    const file = zip.file(resolveEntry(entry.getAttribute('href') || ''));
    const xml = file ? parser.parseFromString(await file.async('string'), 'application/xml') : undefined;
    if (xml && !xml.querySelector('parsererror')) continue;
    if (isNav) entry.setAttribute('properties', properties.filter((value) => value !== 'nav').join(' '));
    if (isNcx) {
      for (const spine of Array.from(document.getElementsByTagName('spine'))) {
        if (spine.getAttribute('toc') === entry.getAttribute('id')) spine.removeAttribute('toc');
      }
      entry.remove();
    }
    repaired = true;
  }
  if (repaired) {
    zip.file(opfPath, new XMLSerializer().serializeToString(document));
    buffer = await zip.generateAsync({ type: 'arraybuffer', compression: 'STORE' });
  }
  const chapterIndices = Array.from(document.getElementsByTagName('itemref')).flatMap((entry, index) =>
    entry.getAttribute('linear') === 'no' ||
    manifest.get(entry.getAttribute('idref'))?.getAttribute('properties')?.split(/\s+/).includes('nav')
      ? []
      : [index],
  );
  return { title, author, buffer, chapters: chapterIndices.length, chapterIndices };
}
