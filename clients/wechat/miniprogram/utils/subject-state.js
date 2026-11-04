/* Decide how the visits page must react when a refresh fails because the
   subject or workspace is no longer valid. Kept pure so the failure modes can
   be checked without a WeChat runtime. */

const STALE_CODES = ['WORKSPACE_CHANGED', 'SUBJECT_REQUIRED', 'SUBJECT_CHANGED', 'ACCESS_DENIED'];

function staleSubject(error, session) {
  const code = error && error.code;
  const status = error && error.status;
  const sessionLost = status === 401 ||
    (!!session && session.account_authenticated === false && !session.authenticated);
  // A bare 409 from the read-only overview/visits requests can only mean the
  // subject context changed; coded business conflicts are not expected here.
  const invalid = STALE_CODES.indexOf(code) >= 0 || status === 403 ||
    (status === 409 && !code) || sessionLost;
  const canSwitch = !!session && session.account_authenticated === true && !sessionLost;
  return {
    invalid,
    clearBanner: invalid,
    // SUBJECT_REQUIRED already re-launches to the subject picker in showError.
    reselect: invalid && canSwitch && code !== 'SUBJECT_REQUIRED',
    login: sessionLost
  };
}

module.exports = {staleSubject, STALE_CODES};
