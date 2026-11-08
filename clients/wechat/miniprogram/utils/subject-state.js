/* Classify patient-subject and workspace failures for pages with cached data. */
const {showError} = require('./format');

const STALE_CODES = ['WORKSPACE_CHANGED', 'SUBJECT_REQUIRED', 'SUBJECT_CHANGED', 'ACCESS_DENIED'];

function staleSubject(error, session, {uncodedConflictIsStale = true} = {}) {
  const code = error && error.code;
  const status = error && error.status;
  const sessionLost = status === 401 ||
    (!!session && session.account_authenticated === false && !session.authenticated);
  // A bare 409 from the read-only overview/visits requests can only mean the
  // subject context changed; coded business conflicts are not expected here.
  const invalid = STALE_CODES.indexOf(code) >= 0 || status === 403 ||
    (uncodedConflictIsStale && status === 409 && !code) || sessionLost;
  const canSwitch = !!session && session.account_authenticated === true && !sessionLost;
  return {
    invalid,
    clearBanner: invalid,
    // SUBJECT_REQUIRED already re-launches to the subject picker in showError.
    reselect: invalid && canSwitch && code !== 'SUBJECT_REQUIRED',
    login: sessionLost
  };
}

async function recoverSubject(page, bootstrap, reLaunch) {
  if (page.data.busy || !page.data.subjectInvalid) return;
  const requestId = page.data.requestId;
  page.setData({busy:true});
  try {
    const session = await bootstrap();
    let url = '/pages/login/index';
    if (session.account_authenticated) url = session.authenticated ? '/pages/patients/index' : '/pages/account/index';
    page.setData({busy:false});
    reLaunch({url});
  } catch (error) {
    showError(page,error,{separateRequestId:true,stayOnPage:true});
    if (!error.requestId) page.setData({requestId});
  }
}

module.exports = {staleSubject, recoverSubject, STALE_CODES};
