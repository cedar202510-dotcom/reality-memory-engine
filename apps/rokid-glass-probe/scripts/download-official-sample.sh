#!/usr/bin/env bash

set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
reference_dir="${project_dir}/reference"
zip_path="${reference_dir}/GlassesBareDevSample.zip"
sample_dir="${reference_dir}/GlassesBareDevSample"
sample_url="https://rokid-ota.oss-cn-hangzhou.aliyuncs.com/toB/Document/CXR_Bare/GlassesBareDevSample.zip"

mkdir -p "${reference_dir}"

if [[ ! -f "${zip_path}" ]]; then
    echo "下载 Rokid 官方 GlassesBareDevSample..."
    curl --fail --location --show-error "${sample_url}" --output "${zip_path}.part"
    mv "${zip_path}.part" "${zip_path}"
else
    echo "已存在：${zip_path}"
fi

if [[ -d "${sample_dir}" ]]; then
    echo "已解压：${sample_dir}"
    exit 0
fi

echo "解压 Sample..."
# 官方 zip 使用 Windows 反斜杠路径；-s 在 macOS 上将其规范化为目录分隔符。
bsdtar -xf "${zip_path}" -C "${reference_dir}" -s '|\\|/|g'

echo "完成：${sample_dir}"
