import { defineStore } from "pinia";
import { ref } from "vue";
import http from "../api/http";

export const useAuthStore = defineStore("auth", () => {
  const token = ref<string | null>(localStorage.getItem("ekb_token"));
  const role = ref<string | null>(localStorage.getItem("ekb_role"));
  const userId = ref<string | null>(localStorage.getItem("ekb_uid"));

  async function login(username: string, password: string) {
    const { data } = await http.post("/api/v1/auth/login", { username, password });
    token.value = data.access_token;
    role.value = data.role;
    userId.value = data.user_id;
    localStorage.setItem("ekb_token", data.access_token);
    localStorage.setItem("ekb_role", data.role);
    localStorage.setItem("ekb_uid", data.user_id);
  }

  function logout() {
    token.value = null;
    role.value = null;
    userId.value = null;
    localStorage.removeItem("ekb_token");
    localStorage.removeItem("ekb_role");
    localStorage.removeItem("ekb_uid");
  }

  const isAdmin = () => role.value === "admin";
  const canKbAdmin = () => role.value === "admin" || role.value === "kb_admin";
  const canUpload = () =>
    role.value === "admin" || role.value === "kb_admin" || role.value === "contributor";

  return { token, role, userId, login, logout, isAdmin, canKbAdmin, canUpload };
});
