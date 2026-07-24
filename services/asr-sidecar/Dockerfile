FROM python:3.12-slim

# 模型大小在构建期可选（tiny/base/small/medium/large-v3）；构建时预下载，首次启动不再联网
ARG ASR_MODEL_SIZE=small
# 可选：HuggingFace 镜像端点（国内构建可 --build-arg HF_ENDPOINT=https://hf-mirror.com）
ARG HF_ENDPOINT=""
ENV ASR_MODEL_SIZE=${ASR_MODEL_SIZE} \
    ASR_DEVICE=cpu \
    ASR_COMPUTE_TYPE=int8 \
    ASR_MODEL_DIR=/models \
    HF_ENDPOINT=${HF_ENDPOINT} \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 预下载模型到 /models（CTranslate2 格式，HuggingFace Hub）。
# 若构建期网络不可达，可跳过此层：运行时挂载模型缓存卷，首次启动自动下载（启动较慢）。
RUN python -c "from faster_whisper import WhisperModel; import os; \
    WhisperModel(os.environ['ASR_MODEL_SIZE'], device='cpu', compute_type='int8', \
                 download_root=os.environ['ASR_MODEL_DIR'])"

COPY app ./app

EXPOSE 8100
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
