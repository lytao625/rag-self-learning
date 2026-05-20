<script setup lang="ts">
import type { UploadFile } from "element-plus";
import { ElMessage } from "element-plus";
import { computed, onMounted, ref, watch } from "vue";
import http from "../api/http";
import { streamChat, type CitationItem } from "../api/sse";
import { useAuthStore } from "../stores/auth";

type KB = {
  id: string;
  name: string;
  description: string;
  embedding_model_id: string;
  chunk_size: number;
  chunk_overlap: number;
  use_rerank: boolean;
  rerank_top_k: number;
  search_top_k: number;
  created_at: string;
};
type Doc = {
  id: string;
  knowledge_base_id: string;
  filename: string;
  content_hash: string;
  status: string;
  created_at: string;
};
type Job = {
  id: string;
  document_id: string;
  status: string;
  progress: number;
  error_message?: string | null;
};
type Session = { id: string; knowledge_base_id: string; title: string; created_at: string };
type Msg = {
  id: string;
  role: string;
  content: string;
  citations_json?: { items?: CitationItem[] } | null;
  created_at: string;
};

const auth = useAuthStore();
const loginVisible = ref(!auth.token);
const loginForm = ref({ username: "admin", password: "admin123" });

const kbs = ref<KB[]>([]);
const kbId = ref<string>("");
const docs = ref<Doc[]>([]);
const sessions = ref<Session[]>([]);
const sessionId = ref<string | null>(null);
const messages = ref<Msg[]>([]);
const citations = ref<CitationItem[]>([]);
const input = ref("");
const sending = ref(false);
const kbForm = ref({ name: "", description: "" });
const uploadRef = ref();
const pollJob = ref<Job | null>(null);
let pollTimer: number | undefined;
const llmInfo = ref({
  llm_model: "",
  embedding_model: "",
  openai_api_base: "",
  has_api_key: false,
});
const kbConfig = ref({
  use_rerank: false,
  rerank_top_k: 5,
  search_top_k: 20,
});
const savingConfig = ref(false);
const searchQ = ref("");
const searchResults = ref<unknown[]>([]);

const canCreateKb = computed(() => auth.canKbAdmin());
const canUpload = computed(() => auth.canUpload());
const canSearch = computed(() => auth.canKbAdmin());

async function doLogin() {
  try {
    await auth.login(loginForm.value.username, loginForm.value.password);
    loginVisible.value = false;
    await bootstrap();
    ElMessage.success("登录成功");
  } catch {
    ElMessage.error("登录失败");
  }
}

function logout() {
  auth.logout();
  loginVisible.value = true;
}

async function bootstrap() {
  const { data } = await http.get<KB[]>("/api/v1/knowledge-bases");
  kbs.value = data;
  if (!kbId.value && data.length) kbId.value = data[0].id;
  try {
    const cfg = await http.get("/api/v1/config/llm");
    llmInfo.value = cfg.data;
  } catch {
    /* ignore */
  }
  await loadSessions();
}

async function loadSessions() {
  const { data } = await http.get<Session[]>("/api/v1/sessions");
  sessions.value = data;
}

async function loadDocs() {
  if (!kbId.value) {
    docs.value = [];
    return;
  }
  const { data } = await http.get<Doc[]>(`/api/v1/knowledge-bases/${kbId.value}/documents`);
  docs.value = data;
}

async function loadMessages() {
  if (!sessionId.value) {
    messages.value = [];
    return;
  }
  const { data } = await http.get<Msg[]>(`/api/v1/sessions/${sessionId.value}/messages`);
  messages.value = data;
  const last = [...data].reverse().find((m) => m.role === "assistant" && m.citations_json?.items);
  citations.value = (last?.citations_json?.items as CitationItem[]) || [];
}

watch(kbId, async () => {
  const kb = kbs.value.find((k) => k.id === kbId.value);
  if (kb) {
    kbConfig.value = {
      use_rerank: kb.use_rerank,
      rerank_top_k: kb.rerank_top_k,
      search_top_k: kb.search_top_k,
    };
  }
  await loadDocs();
  sessionId.value = null;
  messages.value = [];
  citations.value = [];
});

watch(sessionId, loadMessages);

onMounted(async () => {
  if (auth.token) await bootstrap();
});

async function createKb() {
  if (!kbForm.value.name.trim()) return;
  await http.post("/api/v1/knowledge-bases", {
    name: kbForm.value.name,
    description: kbForm.value.description,
  });
  kbForm.value = { name: "", description: "" };
  await bootstrap();
  ElMessage.success("知识库已创建");
}

async function onUploadChange(file: UploadFile) {
  if (file.raw) await onFileChange(file.raw);
}

async function onFileChange(file: File) {
  if (!kbId.value || !canUpload.value) return;
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await http.post<Job>(`/api/v1/knowledge-bases/${kbId.value}/documents`, fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  pollJob.value = data;
  startPoll(data.id);
  await loadDocs();
}

function startPoll(jobId: string) {
  if (pollTimer) window.clearInterval(pollTimer);
  pollTimer = window.setInterval(async () => {
    try {
      const { data } = await http.get<Job>(`/api/v1/jobs/${jobId}`);
      pollJob.value = data;
      if (data.status === "done" || data.status === "failed") {
        window.clearInterval(pollTimer);
        pollTimer = undefined;
        await loadDocs();
      }
    } catch {
      window.clearInterval(pollTimer);
    }
  }, 1500);
}

async function newSession() {
  sessionId.value = null;
  messages.value = [];
  citations.value = [];
}

async function send() {
  if (!kbId.value || !input.value.trim() || sending.value) return;
  sending.value = true;
  const text = input.value.trim();
  input.value = "";
  messages.value = [...messages.value, { id: "local-user", role: "user", content: text, created_at: "" }];
  let acc = "";
  citations.value = [];
  try {
    await streamChat(
      {
        knowledge_base_id: kbId.value,
        session_id: sessionId.value,
        message: text,
        stream: true,
        top_k: 6,
      },
      auth.token!,
      (items) => {
        citations.value = items;
      },
      (delta) => {
        acc += delta;
        const last = messages.value[messages.value.length - 1];
        if (last && last.id === "local-assistant") last.content = acc;
        else
          messages.value = [
            ...messages.value,
            { id: "local-assistant", role: "assistant", content: acc, created_at: "" },
          ];
      },
      async (sid) => {
        sessionId.value = sid;
        await loadSessions();
        await loadMessages();
      },
      (err) => ElMessage.error(err)
    );
  } finally {
    sending.value = false;
  }
}

async function pickSession(id: string) {
  sessionId.value = id;
}

async function removeSession(id: string) {
  await http.delete(`/api/v1/sessions/${id}`);
  if (sessionId.value === id) await newSession();
  await loadSessions();
}

async function removeDoc(doc: Doc) {
  await http.delete(`/api/v1/knowledge-bases/${kbId.value}/documents/${doc.id}`);
  await loadDocs();
  ElMessage.success("已删除");
}

async function saveConfig() {
  if (!kbId.value || savingConfig.value) return;
  savingConfig.value = true;
  try {
    await http.patch(`/api/v1/knowledge-bases/${kbId.value}`, {
      use_rerank: kbConfig.value.use_rerank,
      rerank_top_k: kbConfig.value.rerank_top_k,
      search_top_k: kbConfig.value.search_top_k,
    });
    const kb = kbs.value.find((k) => k.id === kbId.value);
    if (kb) {
      kb.use_rerank = kbConfig.value.use_rerank;
      kb.rerank_top_k = kbConfig.value.rerank_top_k;
      kb.search_top_k = kbConfig.value.search_top_k;
    }
    ElMessage.success("检索配置已保存");
  } catch {
    ElMessage.error("保存失败");
  } finally {
    savingConfig.value = false;
  }
}

async function runSearch() {
  if (!canSearch.value || !kbId.value) return;
  const { data } = await http.post("/api/v1/search", {
    knowledge_base_id: kbId.value,
    query: searchQ.value,
    top_k: 8,
  });
  searchResults.value = data.results;
}
</script>

<template>
  <el-container style="height: 100vh; flex-direction: column">
    <el-header
      style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #eee"
    >
      <strong>企业智能知识库</strong>
      <div>
        <span v-if="auth.token" style="margin-right: 12px; color: #666"
          >{{ auth.role }} / {{ auth.userId?.slice(0, 8) }}</span
        >
        <el-button v-if="auth.token" size="small" @click="logout">退出</el-button>
      </div>
    </el-header>

    <el-container style="flex: 1; overflow: hidden">
      <el-aside width="220px" style="border-right: 1px solid #eee; padding: 8px; overflow: auto">
        <div style="margin-bottom: 8px; font-weight: 600">会话</div>
        <el-button type="primary" size="small" style="width: 100%; margin-bottom: 8px" @click="newSession"
          >新会话</el-button
        >
        <el-menu :default-active="sessionId || ''" @select="pickSession">
          <el-menu-item v-for="s in sessions" :key="s.id" :index="s.id">
            <div style="display: flex; justify-content: space-between; width: 100%; align-items: center">
              <span style="overflow: hidden; text-overflow: ellipsis">{{ s.title }}</span>
              <el-button link type="danger" @click.stop="removeSession(s.id)">删</el-button>
            </div>
          </el-menu-item>
        </el-menu>
      </el-aside>

      <el-aside width="30%" style="border-right: 1px solid #eee; padding: 8px; overflow: auto">
        <div style="font-weight: 600; margin-bottom: 8px">检索与引用</div>
        <el-empty v-if="!citations.length" description="发送问题后将显示引用片段" />
        <el-card v-for="(c, i) in citations" :key="c.chunk_id" shadow="never" style="margin-bottom: 8px">
          <template #header>
            <span>#{{ i + 1 }} {{ (c.metadata as any)?.source }}</span>
            <el-tag size="small" style="float: right">score {{ c.score }}</el-tag>
          </template>
          <pre style="white-space: pre-wrap; margin: 0; font-size: 12px">{{ c.content }}</pre>
        </el-card>
      </el-aside>

      <el-main style="padding: 8px; display: flex; flex-direction: column; min-height: 0">
        <div style="flex: 1; overflow: auto; margin-bottom: 8px">
          <div v-for="m in messages" :key="m.id" style="margin-bottom: 12px">
            <el-tag size="small" :type="m.role === 'user' ? 'primary' : 'success'">{{ m.role }}</el-tag>
            <pre style="white-space: pre-wrap; margin: 4px 0 0">{{ m.content }}</pre>
          </div>
        </div>
        <el-input
          v-model="input"
          type="textarea"
          :rows="3"
          placeholder="输入问题，Ctrl+Enter 发送"
          @keydown.ctrl.enter="send"
        />
        <el-button type="primary" style="margin-top: 8px; align-self: flex-end" :loading="sending" @click="send"
          >发送</el-button
        >
      </el-main>

      <el-aside width="28%" style="padding: 8px; overflow: auto; border-left: 1px solid #eee">
        <div style="font-weight: 600; margin-bottom: 8px">知识库与配置</div>
        <el-select v-model="kbId" placeholder="选择知识库" style="width: 100%; margin-bottom: 8px">
          <el-option v-for="k in kbs" :key="k.id" :label="k.name" :value="k.id" />
        </el-select>

        <el-card v-if="canCreateKb" shadow="never" style="margin-bottom: 8px">
          <template #header>新建知识库</template>
          <el-input v-model="kbForm.name" placeholder="名称" />
          <el-input v-model="kbForm.description" placeholder="描述" style="margin-top: 6px" />
          <el-button type="primary" size="small" style="margin-top: 6px" @click="createKb">创建</el-button>
        </el-card>

        <el-card shadow="never" style="margin-bottom: 8px">
          <template #header>文档上传</template>
          <el-upload
            v-if="canUpload && kbId"
            :auto-upload="false"
            :show-file-list="false"
            accept=".pdf,.docx,.txt,.md,.xlsx"
            @change="onUploadChange"
          >
            <el-button size="small">选择文件</el-button>
          </el-upload>
          <div v-if="pollJob" style="margin-top: 6px; font-size: 12px">
            任务 {{ pollJob.status }} {{ pollJob.progress }}%
            <span v-if="pollJob.error_message" style="color: red">{{ pollJob.error_message }}</span>
          </div>
        </el-card>

        <el-card shadow="never" style="margin-bottom: 8px">
          <template #header>文档列表</template>
          <el-table :data="docs" size="small" height="200">
            <el-table-column prop="filename" label="文件" />
            <el-table-column width="70" label="">
              <template #default="{ row }">
                <el-button v-if="canUpload" link type="danger" @click="removeDoc(row)">删</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card shadow="never" style="margin-bottom: 8px">
          <template #header>模型（服务端环境变量）</template>
          <div style="font-size: 12px; line-height: 1.6">
            <div>LLM: {{ llmInfo.llm_model }}</div>
            <div>Embedding: {{ llmInfo.embedding_model }}</div>
            <div>Base: {{ llmInfo.openai_api_base }}</div>
            <div>已配置 Key: {{ llmInfo.has_api_key ? "是" : "否" }}</div>
          </div>
        </el-card>

        <el-card v-if="canSearch" shadow="never">
          <template #header>调试检索</template>
          <el-input v-model="searchQ" placeholder="关键词" />
          <el-button size="small" style="margin-top: 6px" @click="runSearch">检索</el-button>
          <pre style="font-size: 11px; max-height: 200px; overflow: auto">{{ JSON.stringify(searchResults, null, 2) }}</pre>
        </el-card>
        
        <el-card shadow="never" style="margin-bottom: 8px">
          <template #header>检索配置</template>
          <el-form label-width="80px" size="small">
            <el-form-item label="启用重排序">
              <el-switch v-model="kbConfig.use_rerank" />
            </el-form-item>
            <el-form-item label="重排数量" v-if="kbConfig.use_rerank">
              <el-input-number v-model="kbConfig.rerank_top_k" :min="1" :max="20" />
            </el-form-item>
            <el-form-item label="初始召回数">
              <el-input-number v-model="kbConfig.search_top_k" :min="5" :max="100" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" size="small" :loading="savingConfig" @click="saveConfig">保存配置</el-button>
            </el-form-item>
          </el-form>
        </el-card>

      </el-aside>
    </el-container>
  </el-container>

  <el-dialog v-model="loginVisible" title="登录" width="400px" :close-on-click-modal="false">
    <el-form label-width="80px">
      <el-form-item label="用户名">
        <el-input v-model="loginForm.username" />
      </el-form-item>
      <el-form-item label="密码">
        <el-input v-model="loginForm.password" type="password" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button type="primary" @click="doLogin">登录</el-button>
    </template>
    <div style="font-size: 12px; color: #888">
      演示账号：admin/admin123；kbadmin/kbadmin123；contributor/contrib123；user/user123
    </div>
  </el-dialog>
</template>
