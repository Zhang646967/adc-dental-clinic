App({
  globalData: { review: null },
  onLaunch() { require('./utils/api').reset(); }
});
