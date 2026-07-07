# 每日美国 50 州天气地图

## 手动生成

```bash
./weather_map_automation/run_daily_weather_map.sh
```

输出目录：

- `daily_us_weather_maps/us_weather_map_YYYY-MM-DD.png`
- `daily_us_weather_maps/latest_us_weather_map.png`
- `daily_us_weather_maps/weather_data_YYYY-MM-DD.json`

## 钉钉机器人配置

复制配置模板：

```bash
cp weather_map_automation/dingtalk_config.example.json weather_map_automation/dingtalk_config.json
```

填写：

- `webhook`：钉钉自定义机器人的 Webhook 地址。
- `secret`：如果机器人开启“加签”，填写 `SEC...`；未开启可留空。
- `image_base_url`：可选。图片如果会同步到公网目录，填公网目录前缀，钉钉消息里会显示图片。
- `image_url`：可选。固定公网图片地址，优先级高于 `image_base_url`。
- `at_mobiles`：可选，需要 @ 的手机号列表。
- `is_at_all`：可选，是否 @ 所有人。

测试发送：

```bash
./weather_map_automation/run_daily_weather_map.sh --send-dingtalk
```

说明：钉钉机器人无法读取本机文件路径。要在钉钉消息内直接显示图片，需要把生成的 PNG 同步到一个公网可访问地址，并配置 `image_base_url` 或 `image_url`。

## GitHub Pages 图片托管

复制配置模板：

```bash
cp weather_map_automation/github_pages_config.example.json weather_map_automation/github_pages_config.json
```

填写：

- `owner`：GitHub 用户名。
- `repo`：GitHub Pages 仓库名。
- `branch`：通常是 `main`。
- `pages_base_url`：GitHub Pages 网站地址。
- `remote_dir`：图片上传目录，默认 `daily_us_weather_maps`。
- `token`：有该仓库 `Contents: Read and write` 权限的 GitHub Token。

生成、上传并发送钉钉：

```bash
./weather_map_automation/run_daily_weather_map.sh --upload-github-pages --send-dingtalk
```
