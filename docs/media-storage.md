# 统一媒体存储

管理后台 /admin/storage/settings 支持 storage_mode=od_first、r2_first、balanced，od_weight/r2_weight 为 1–100，fallback_enabled 控制准备失败时尝试另一端，od_enabled 控制是否允许新上传到 OD。配置只影响新上传，已有 public_url 不重写。R2 仍保留 9,000,000,000 字节阈值。

管理后台使用 /admin/media/direct/prepare 和 /confirm，均要求管理员权限。签名票据绑定用户、存储后端、唯一对象路径、大小、内容类型、摘要与 15 分钟有效期。OD 使用顺序 5 MiB 分片，不向上传地址发送站点 Cookie、Authorization 或 S3 专用头；R2 原有直传保持兼容。

OD 确认检查云端大小、QuickXorHash 和前 64 字节内容特征；QuickXorHash 是传输完整性校验，不是密码学签名。SHA-256 作为客户端提交的摘要记录。R2 检查头部、大小和元数据。文件校验失败会尝试清理云端对象且不建媒体记录。

支持原有图片和 PDF/TXT/EPUB/ZIP、MP3/MP4/WebM/OGG/WAV/FLAC，单文件上限 100 MiB；不开放 HTML/SVG、脚本或可执行文件。评论上传仍由既有图片验证入口限制。

OD 上传控制面代码在 main 的 experiments/onedrive-media/upload_bridge.py，仅 127.0.0.1:8812/internal/od 可访问，要求 OD_BRIDGE_KEY；公开 Nginx 阻断 /internal/。API 与 OD 两个 systemd 服务均通过 root 私有 EnvironmentFile=/etc/replow/od-bridge.env 加载同一随机密钥。不要把密钥、OAuth 凭据或签名网址放进 Git、日志或前端环境变量。

OAuth 令牌仅由 OD 服务维护，API 不读取该文件。OD 上传自动返回 https://drive.4z.ink/media/分类/唯一文件名。原 /media/upload 中转入口也遵循同一存储策略，供评论等已有功能使用。

运行 python -m unittest discover -s tests -p test_media_od.py 验证分流、完整性、权限绑定及删除失败保留记录。测试使用隔离的存储桩，不写生产数据；另须运行真实两端上传/下载/删除验证。
