App({
  globalData: { review: null, bookingIntent: null, returnSource: null },
  onLaunch() { require('./utils/api').reset(); }
});
