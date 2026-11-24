const API_BASE = '/api';
export async function api(path, options = {}) {
  const token = localStorage.getItem('campusToken');
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const error = new Error(typeof detail === 'string' ? detail : (detail?.message || '请求失败'));
    error.detail = detail;
    error.status = response.status;
    throw error;
  }
  return data;
}
export const get = (path) => api(path);
export const post = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body ?? {}) });
