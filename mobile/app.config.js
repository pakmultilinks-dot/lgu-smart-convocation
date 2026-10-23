/**
 * Isolate the installable Expo EAS preview from the university release app.
 * EAS Build's preview profile sets APP_VARIANT=preview in eas.json.
 * No API URL or credential is baked into the standalone APK.
 */
module.exports = ({ config }) => {
  if (process.env.APP_VARIANT !== "preview") return config;
  return {
    ...config,
    name: "LGU Convocation",
    android: {
      ...config.android,
      package: "pk.edu.lgu.smartconvocation.preview",
      usesCleartextTraffic: false,
    },
  };
};
