App({
  globalData: { review: null, bookingIntent: null },
  onLaunch() { require('./utils/api').reset(); }
});
