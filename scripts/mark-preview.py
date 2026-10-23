from pathlib import Path
p=Path("dist/index.html")
s=p.read_text().replace("</head>",'<meta name="robots" content="noindex,nofollow"><meta name="silune-environment" content="preview"></head>')
s=s.replace("<body>",'<body><div style="position:fixed;right:12px;bottom:12px;z-index:999999;padding:6px 12px;border-radius:20px;background:#fef3c7;color:#78350f;font:12px system-ui;pointer-events:none">PREVIEW · 测试环境</div>')
p.write_text(s)
