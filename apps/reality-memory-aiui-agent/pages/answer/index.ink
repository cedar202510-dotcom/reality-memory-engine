<script type="application/json" def>
{
  "navigationBarTitleText": "RealGit",
  "description": "当用户询问自己的现实记忆、物品位置、个人偏好、任务、近期活动或记忆来源时，调用 RealGit 后端查询真实记忆并展示回答。不得自行猜测用户的个人事实。",
  "schema": {
    "data": {
      "type": "object",
      "properties": {
        "message": {
          "type": "string",
          "minLength": 1,
          "description": "用户向 RealGit 提出的原始问题，必须保留物品名称、时间和上下文，不得改写事实条件。"
        },
        "session_id": {
          "type": "string",
          "description": "可选的 AIUI 会话编号；未提供时由页面复用本地短期会话。"
        }
      },
      "required": [
        "message"
      ]
    }
  }
}
</script>

<script setup>
import { askRealGit, speakReply } from "../../lib/realgit-client.js";

function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}

export default {
  data: {
    state: "loading",
    reply: "",
    errorTitle: "",
    errorHint: ""
  },

  async onLoad(query) {
    const input = query || {};
    const message = cleanText(input.message);
    if (!message) {
      this.setData({
        state: "error",
        errorTitle: "没有收到要查询的问题",
        errorHint: "请重新向乐奇说出你的问题"
      });
      return;
    }

    this.setData({
      state: "loading",
      reply: "",
      errorTitle: "",
      errorHint: ""
    });

    try {
      const result = await askRealGit(message, cleanText(input.session_id));
      this.setData({
        state: "success",
        reply: result.reply
      });
      speakReply(result.reply);
    } catch (error) {
      console.error("RealGit AIUI request failed", error);
      this.setData({
        state: "error",
        errorTitle: "暂时没能连接到你的记忆",
        errorHint: "请稍后再试"
      });
    }
  }
};
</script>

<page>
  <view class="answer-surface">
    <view class="identity-row">
      <view class="presence-ring">
        <view class="presence-dot"></view>
      </view>
      <text class="brand">REALGIT</text>
    </view>

    <view class="answer-content" ink:if="{{ state === 'loading' }}">
      <text class="status">正在查询你的现实记忆</text>
      <view class="loading-line"></view>
    </view>

    <view class="answer-content" ink:elif="{{ state === 'success' }}">
      <text class="reply">{{ reply }}</text>
      <text class="provenance">来自你的现实记忆</text>
    </view>

    <view class="answer-content" ink:else>
      <text class="error-title">{{ errorTitle }}</text>
      <text class="error-hint">{{ errorHint }}</text>
    </view>
  </view>
</page>

<style>
.answer-surface {
  display: flex;
  width: 448px;
  min-height: 167px;
  flex-direction: column;
  box-sizing: border-box;
  padding: 18px 20px;
  background-color: transparent;
  color: #40ff5e;
  letter-spacing: 0;
}

.identity-row {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 9px;
}

.presence-ring {
  display: flex;
  width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  border: 1px solid rgba(64, 255, 94, 0.68);
  border-radius: 50%;
}

.presence-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background-color: #40ff5e;
}

.brand {
  font-size: 11px;
  line-height: 14px;
  color: rgba(64, 255, 94, 0.72);
}

.answer-content {
  display: flex;
  flex: 1;
  flex-direction: column;
  justify-content: center;
  margin-top: 12px;
  padding-left: 27px;
  border-left: 2px solid rgba(64, 255, 94, 0.68);
}

.reply,
.error-title {
  max-width: 360px;
  font-size: 20px;
  line-height: 28px;
  color: #40ff5e;
}

.status,
.error-hint,
.provenance {
  font-size: 12px;
  line-height: 18px;
  color: rgba(64, 255, 94, 0.66);
}

.provenance,
.error-hint {
  margin-top: 7px;
}

.loading-line {
  width: 82px;
  height: 2px;
  margin-top: 10px;
  background-color: rgba(64, 255, 94, 0.58);
}
</style>
