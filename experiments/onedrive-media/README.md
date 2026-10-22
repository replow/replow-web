# OneDrive 媒体固定链接试验（仅 preview）

## v26.10.22-u2：无需 OpenList 常驻进程的授权方式

新增 openlist_auth.py 和 authorize_openlist.py，对接 OpenList 官方 Online API；
文件查询和直链仍直接走微软 Graph，不安装 OpenList，不新增生产后台依赖。

已从 Azure 实测：
- 官方页面 HTTP 200。
- /onedrive/requests 返回 HTTP 200，目标是 login.microsoftonline.com，
  并设置官方回调需要的 cookie；不要把服务器获取的微软 URL 直接交给另一浏览器，
  应在自己的浏览器从 https://api.oplist.org/ 开始操作。
- /onedrive/renewapi 无凭据时拒绝请求；已完成真实授权续期和媒体根目录验证。
- 34 项测试通过，包含真实伪终端隐藏输入测试；另有独立真实账号/文件验证。

### 授权与导入

1. 打开 https://api.oplist.org/，选择 OneDrive 个人版，勾选使用 OpenList 提供的参数，
   点击获取 Token，并在微软页面登录实际保存媒体的账号。
2. 默认应用目前请求 offline_access 和 Files.ReadWrite.All，范围包含账号文件读写，
   并不只限媒体目录。当前程序仅实现读取。由用户在微软同意页决定是否授权。
3. 在此目录配置 OD_DRIVE_ID、OD_ROOT_ITEM_ID、OD_TOKEN_FILE（存放到仓库外）。
4. 在交互终端执行：

       .venv/bin/python authorize_openlist.py import

   在隐藏输入提示下粘贴 Refresh Token，不要粘贴 Access Token 或整条回调 URL，
   不要把令牌放进命令参数、聊天、截图或工单。
   导入会先续期并验证正确的个人 drive 和专用本地文件夹，验证成功才保存。
5. 真正测试在线续期：

       .venv/bin/python authorize_openlist.py check

这两条命令只导入和验证，不启动常驻服务、不更改 DNS 或生产配置。
不带凭据检查官方入口可运行 authorize_openlist.py probe。

Online API 当前实现使用 GET /onedrive/renewapi，参数是 driver_txt=onedrive_pr、
server_use=true 和 refresh_ui。令牌通过 HTTPS 发给官方续期服务；这是授权模式的一部分。
我们不记录请求完整 URL、不打印原始错误，也不跟随续期接口重定向。
官方结果没有 expires_in，因此访问令牌保守复用 15 分钟，并在 Graph 401 时立即续期；
旋转后的 Refresh Token 原子保存，文件权限 0600；限流时持久化等待时间。
与此独立，文件直链仍使用下方的短缓存和有效性验证。

参考实现：
- https://github.com/OpenListTeam/OpenList/blob/main/drivers/onedrive/util.go
- https://github.com/OpenListTeam/OpenList-APIPages/blob/main/src/driver/onedrive_oa.ts



本目录是独立后端 PoC，不参与 Astro 构建，不替换 R2，不发布 GitHub Release。
代码保留 preview，不修改生产 API 或 main；部署只新增独立 systemd 服务和 drive Nginx 入口，
后端仅监听回环地址。配置与回滚见 deploy/README.md。

目标映射：公开媒体目录中的 images/a.webp → https://drive.4z.ink/images/a.webp。
固定的是入口路径；响应为 302，浏览器随后直接从微软下载，图片字节不经过 Azure。
移动、重命名或删除源文件会影响路径；目前没有实现重命名后的永久别名。
2026-10-22 已上线 drive.4z.ink：CF SaaS hostname/SSL 均 active，
DNS CNAME 到 api.4z.ink，沿用现有 CF 优选。新主机需要先临时指向 SaaS 接入 CNAME
完成激活和签发，再恢复优选；禁止直连源站。

## 当前验证状态

- 自动测试覆盖缓存命中、提前刷新、过期换链、直链提前失效、并发请求、
  Graph 限流、目录边界、共享快捷方式、下载目标白名单和缺少授权时关闭访问。
- 已导入独立网站授权并验证真实在线续期；ChatGPT SharePoint 连接不作为网站凭据。
- 已在 OD 准备 website-media 试验目录和 preview-probe.txt。
- 源站 HTTPS、正常 DNS 公网和指定优选边缘均验证：302、缓存命中、微软下载 200 且内容匹配。
- 真实缓存过期重新取链和后台刷新已验证；目录根路径和缺失文件 404，POST 403。
- CF 跳过此域名缓存，响应 no-store；宝塔响应过滤仅豁免本服务经校验的 302。
- 微软实际直链失效时刻与国内各运营商下载性能尚未测量。

## 缓存方式

微软没有为全部下载 URL 提供稳定的精确过期字段，官方说明不能把 downloadUrl
当作长期可缓存的地址。因此这是保守复用试验，不承诺缓存一直持续到微软到期：

1. 默认最多复用 120 秒（可设 15–300 秒）；如果 URL 带可识别的更早到期时间，
   额外预留 30 秒。
2. 约 70% 缓存周期时由请求或后台循环刷新；后台每 5 秒扫描缓存，
   只维护最近 10 分钟使用的条目，最多 2048 项，单进程单 worker。
3. 每次跳转前向缓存 URL 发 HEAD 检查。遇 401/403/404/410，立即失效并重新取链。
   不支持 HEAD 时仅以 Range 请求验证，不缓冲或转发文件内容。
4. 302 和错误均 no-store，浏览器/CDN 不保存旧 Location。
5. Graph 429/503 遵守 Retry-After，避免请求风暴；链接仍有效且检查通过时可短暂复用。
6. 无法检查、授权失败或未知下载域名时关闭访问。微软仍可能在检查和访客请求之间撤销链接，
   因此不能保证绝无瞬时失效。

## 本地启动

需要 Python 3.11+。在此目录创建独立环境：

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python -m unittest discover -v

复制 .env.example 到本地 .env 并填入对应的 drive ID 和媒体文件夹 item ID。
只加载你自己填写的文件：

    set -a
    . ./.env
    set +a

令牌默认存于 ~/.local/state/replow-od-preview/token.json，目录 0700、文件 0600。
不要把令牌放进仓库、Astro PUBLIC_ 变量、静态快照或日志。
网站启动时不调用 ChatGPT 插件；它自己通过 Microsoft Graph 访问 OD。

## 备选：自有应用的一次性微软授权

在你自己的 Microsoft Entra 应用注册中，使用支持个人微软账号的公共客户端，
启用 public client flow，授予委托 Files.Read。工具请求 offline_access，
以便后端续期。Client ID 是公开的应用标识，无需把密码或 token 发到聊天里。

    .venv/bin/python authorize.py start --client-id YOUR_OWN_CLIENT_ID

打开命令返回的微软登录地址，在微软页面完成同意，然后执行：

    .venv/bin/python authorize.py poll

poll 每次只请求一次，并遵守微软返回的轮询间隔；没有常驻的公开授权入口。
保存凭据前会校验登录账号的 OneDrive 和配置的 drive ID、媒体目录是否一致。

    .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8812 --workers 1 --no-access-log

在另一个终端测试：

    curl -sS http://127.0.0.1:8812/healthz
    curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8812/preview-probe.txt
    curl -fsSL http://127.0.0.1:8812/preview-probe.txt

首个固定路径请求应 302；重复请求应命中缓存；最后一条应得到试验文件内容。
不要使用 curl -v、curl -i 或将含 Location 的响应头上传日志，以免泄露临时下载地址。
实际过期验证应观察计数或 X-OD-Cache，隐藏完整 URL 和令牌。

## 访问边界和限制

只有所配置媒体目录下的文件会提供链接；没有列表、上传、删除或代理任意 URL 接口。
专用目录中的文件视为公开媒体；不要放备份、配置或私人照片。
父目录校验拒绝跨 drive 和共享快捷方式，下载主机只允许已知微软域名。
Files.Read 本身覆盖该用户的文件读取能力；媒体目录隔离由此服务执行，不是微软的单目录授权。
路径校验拒绝隐藏文件、路径穿越和二次编码；当前不支持文件名中含百分号、反斜杠或冒号。

预览配置将文件下载到微软域名，所以最终响应的 CORS、文件展示方式和国内网络质量由微软决定。
drive.4z.ink 的 CF 优选只改善固定入口的请求，不会自动加速 302 后的微软下载域名。
正式接入前还需测试常用图片格式、移动端、实际缓存周期和实际下载速度。

参考：
- https://learn.microsoft.com/en-us/graph/api/driveitem-get-content?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/api/resources/driveitem?view=graph-rest-1.0
- https://learn.microsoft.com/en-us/graph/throttling
- https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code
