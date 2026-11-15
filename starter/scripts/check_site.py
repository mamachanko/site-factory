#!/usr/bin/env python3
"""Check the static site's HTML structure and local asset/link targets; no packages."""
from html.parser import HTMLParser
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.links = []
        self.labels = set()
        self.controls = []
        self.tags = []
        self.errors = []
        self.title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if tag == 'html' and not attrs.get('lang'):
            self.errors.append('html needs a lang attribute')
        if tag == 'title':
            self.title = True
        if tag == 'img' and 'alt' not in attrs:
            self.errors.append('img needs alt text')
        if identity := attrs.get('id'):
            if identity in self.ids:
                self.errors.append(f'duplicate id: {identity}')
            self.ids.add(identity)
        if tag == 'label' and attrs.get('for'):
            self.labels.add(attrs['for'])
        if tag in ('input', 'select', 'textarea') and attrs.get('type') != 'hidden':
            self.controls.append(attrs)
        for key in ('href', 'src'):
            if attrs.get(key):
                self.links.append(attrs[key])


def check(root):
    errors = []
    pages = sorted(root.rglob('*.html'))
    if not (root / 'index.html').is_file():
        errors.append('missing index.html')
    for page in pages:
        doc = Document()
        doc.feed(page.read_text(encoding='utf-8'))
        for required in ('html', 'head', 'title', 'main'):
            if required not in doc.tags:
                doc.errors.append(f'missing {required}')
        for control in doc.controls:
            if control.get('id') not in doc.labels and not control.get('aria-label') and not control.get('aria-labelledby'):
                doc.errors.append('form control needs an accessible label')
        for link in doc.links:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                continue
            if url.path.startswith('/'):
                doc.errors.append(f'use relative links for project Pages: {link}')
                continue
            target = (page.parent / unquote(url.path)).resolve() if url.path else page.resolve()
            if not target.is_relative_to(root.resolve()):
                doc.errors.append(f'link leaves site directory: {link}')
                continue
            if target.is_dir():
                target /= 'index.html'
            if not target.is_file():
                doc.errors.append(f'missing link target: {link}')
            elif url.fragment:
                target_doc = doc
                if target != page.resolve() and target.suffix == '.html':
                    target_doc = Document()
                    target_doc.feed(target.read_text(encoding='utf-8'))
                if unquote(url.fragment) not in target_doc.ids:
                    doc.errors.append(f'missing fragment: {link}')
        errors.extend(f'{page.relative_to(root)}: {error}' for error in doc.errors)
    return errors


if __name__ == '__main__':
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'site'
    errors = check(root)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        sys.exit(1)
    print('Static site checks passed: HTML landmarks, labels, IDs, and local links/assets.')
