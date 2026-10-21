"""Prepare scoped Nginx routes; never send gallery misses to the forum rate limiter."""
import argparse
from pathlib import Path


def configure(text, surface):
    marker = '# handraw-public-routes-v2'
    if marker in text:
        return text
    if text.count('    location / {') != 1:
        raise ValueError('Expected one existing catch-all location')
    if surface == 'main':
        routes = '''    # handraw-public-routes-v2
    location ^~ /gallery/ {
        return 302 https://static.handraw-style.com$uri?web=2&$args;
    }
    location ^~ /studio/assets/ {
        alias /home/yang0/handraw-data/public/current/assets/;
        expires 5m;
        try_files $uri =404;
    }
'''
    else:
        routes = '''    # handraw-public-routes-v2
    location ^~ /handraw-web/releases/ {
        alias /home/yang0/handraw-data/public/releases/;
        add_header Access-Control-Allow-Origin "*" always;
        expires 1y;
        try_files $uri =404;
    }
    location ^~ /gallery/ {
        alias /home/yang0/handraw-data/public/current/gallery/;
        add_header Access-Control-Allow-Origin "*" always;
        add_header Cache-Control "no-cache" always;
        try_files $uri =404;
    }
    location ^~ /images/ {
        alias /home/yang0/projectHome/handraw-static/images/;
        add_header Access-Control-Allow-Origin "*" always;
        expires 1d;
        try_files $uri =404;
    }
    location ^~ /data/ {
        alias /home/yang0/projectHome/handraw-static/data/;
        add_header Access-Control-Allow-Origin "*" always;
        expires 5m;
        try_files $uri =404;
    }
'''
    return text.replace('    location / {', routes + '\n    location / {', 1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('surface', choices=['main', 'static'])
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.write_text(configure(args.input.read_text(), args.surface), encoding='utf-8')
