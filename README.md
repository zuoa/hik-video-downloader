# 海康 NVR 录像下载工具

一个基于 PySide6 和 PySide6-Fluent-Widgets 的桌面程序，用于快速连接海康威视 NVR，通过 ISAPI 检索录像并下载录像片段。

## 功能

- 快速填写 NVR 地址、端口、HTTPS、账号密码和通道号
- 使用 `/ISAPI/System/deviceInfo` 测试连接
- 使用 `/ISAPI/ContentMgmt/search` 按通道和时间范围检索录像
- 使用 `/ISAPI/ContentMgmt/download` 按检索到的 `playbackURI` 下载录像
- 支持 Basic 和 Digest 认证自动尝试
- 录像结果列表、下载进度条、运行日志

## 安装运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m hik_video_download
```

如果只想安装依赖、不安装当前包，请使用源码路径运行：

```bash
pip install -r requirements.txt
export PYTHONPATH=src
python -m hik_video_download
```

也可以安装为可执行命令：

```bash
pip install -e .
hik-video-download
```

## 使用说明

1. 填写 NVR 主机、端口、用户名、密码。
2. 填写录像通道。常见 NVR 主码流通道为 `101`、`201`、`301`，分别对应第 1、2、3 路；不同设备可能不同。
3. 选择开始和结束时间，点击“检索录像”。
4. 在结果列表中选择片段，点击“下载所选”。

下载文件默认保存为 `.ps`。这是海康 ISAPI 下载接口常见返回格式；如需 MP4，可后续使用 FFmpeg 转码。

## 兼容性说明

海康不同固件对 ISAPI 的细节支持不完全一致。本程序按公开 ISAPI 方式实现：

- 检索：`POST /ISAPI/ContentMgmt/search`
- 下载：优先 `GET /ISAPI/ContentMgmt/download` 携带 `downloadRequest` XML，失败后回退 `PUT`

如果设备禁用了 ISAPI、账号没有回放权限、通道号不匹配，检索或下载会失败并在日志里显示 HTTP 错误。
