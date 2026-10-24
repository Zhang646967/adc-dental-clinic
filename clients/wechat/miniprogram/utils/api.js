const config = require('../config');
let cookies = {};
let session = {};
let epoch = 0;

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

function reset() { cookies = {}; session = {}; epoch += 1; }

function request(path, method = 'GET', data = {}) {
  const requestedEpoch=epoch;
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
        if(requestedEpoch!==epoch){
          const error=new Error('就诊人或会话已变化，请在当前患者页面重新核对结果。');error.code='SUBJECT_CHANGED';reject(error);return;
        }
        absorb(response);
        const body = response.data || {};
        if (response.statusCode >= 200 && response.statusCode < 300 && body.ok === true) {
          if (body.data && body.data.csrf_token) {
            if(session.workspace_id!==body.data.workspace_id || session.subject_revision!==body.data.subject_revision || session.authenticated!==body.data.authenticated){epoch+=1;getApp().globalData.review=null;}
            session = body.data;
            if (!session.authenticated) getApp().globalData.review = null;
          }
          resolve(body.data);
        } else {
          const message = body.message || body.error || (response.statusCode === 429 ? '操作频繁，请稍后重试。' : '服务暂时无法办理，请稍后核对。');
          const responseHeaders = response.header || {};
          const requestId = body.request_id || responseHeaders['X-Request-ID'] || responseHeaders['x-request-id'];
          const error = new Error(message + (requestId ? `（查询编号 ${requestId}）` : ''));
          error.status = response.statusCode;error.code=body.code;
          if(['SUBJECT_REQUIRED','WORKSPACE_CHANGED','ACCESS_DENIED'].includes(body.code))getApp().globalData.review=null;
          if (response.statusCode === 401) { epoch+=1;session = {}; getApp().globalData.review = null; }
          reject(error);
        }
      },
      fail() { const error=new Error('连接中断，结果尚未确认。若刚刚提交，请先查看对应业务清单，再核对是否需要重试。');error.code='NETWORK_UNCONFIRMED';reject(error); }
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
function showSubject(page){
  page.setData({patientName:session.patient_name||'',patientCapacity:session.acting_capacity||'',patientDelegated:!!session.delegated});
}
async function selectSubject(subject){
  const next=await request('patients/select/','POST',{subject});
  getApp().globalData.review=null;return next;
}
module.exports = {request, bootstrap, signIn, signOut, sessionInfo, reset, showSubject, selectSubject};
