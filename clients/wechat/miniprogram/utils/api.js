const config = require('../config');
let cookies = {};
let session = {};

function absorb(response) {
  const raw = response.cookies || [];
  raw.forEach(value => {
    const pair = value.split(';')[0];
    const at = pair.indexOf('=');
    if (at > 0) {
      const key = pair.slice(0, at), val = pair.slice(at + 1);
      if (val) cookies[key] = val; else delete cookies[key];
    }
  });
}

function reset() { cookies = {}; session = {}; }

function request(path, method = 'GET', data = {}) {
  return new Promise((resolve, reject) => {
    const header = { 'content-type': 'application/x-www-form-urlencoded' };
    const jar = Object.keys(cookies).map(k => `${k}=${cookies[k]}`).join('; ');
    if (jar) header.Cookie = jar;
    if (method !== 'GET') {
      header['X-CSRFToken'] = session.csrf_token || '';
      header['X-ADC-Workspace'] = session.workspace_token || '';
    }
    wx.request({url: `${config.apiBase}/api/mini/v1/${path}`, method, data, header,
      success(response) {
        absorb(response);
        const body = response.data || {};
        if (response.statusCode >= 200 && response.statusCode < 300 && body.ok === true) {
          if (body.data && body.data.csrf_token) {
            session = body.data;
            if (!session.authenticated) getApp().globalData.review = null;
          }
          resolve(body.data);
        } else {
          const message = body.message || body.error || (response.statusCode === 429 ? '操作频繁，请稍后重试。' : '服务暂时无法办理，请稍后核对。');
          const responseHeaders = response.header || {};
          const requestId = body.request_id || responseHeaders['X-Request-ID'] || responseHeaders['x-request-id'];
          const error = new Error(message + (requestId ? `（查询编号 ${requestId}）` : ''));
          error.status = response.statusCode;
          if (response.statusCode === 401) { session = {}; getApp().globalData.review = null; }
          reject(error);
        }
      },
      fail() { reject(new Error('连接中断，结果尚未确认。若刚刚提交，请先查看“我的预约”或“我的候补”，再核对是否需要重试。')); }
    });
  });
}

async function bootstrap() { return request('session/'); }
async function signIn(username, password) {
  await bootstrap();
  return request('login/', 'POST', {username, password});
}
async function signOut() {
  await request('logout/', 'POST'); reset(); getApp().globalData.review = null;
}
function sessionInfo() { return session; }
module.exports = {request, bootstrap, signIn, signOut, sessionInfo, reset};
