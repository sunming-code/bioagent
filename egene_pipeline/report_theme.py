"""Offline presentation shared by integrated reports."""
from html import escape
from pathlib import Path


CSS = Path(__file__).with_name('report_theme.css').read_text(encoding='utf-8')


def folio(label):
    return ('<div class="folio"><span class="imprint">BioAgent</span>'
            f'<span>{escape(label)}</span></div>')


def document(title, label, body):
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(title)}</title><style>{CSS}</style></head><body><main class="digest">'
            f'{folio(label)}<header><h1>{escape(title)}</h1></header>{body}</main></body></html>')
