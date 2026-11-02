/**
 * Isolate the installable Expo EAS preview from the university release app.
 * EAS Build's preview profile sets APP_VARIANT=preview in eas.json.
 * The preview includes its public test-server address, never credentials.
 */
module.exports = ({ config }) => {
  if (process.env.APP_VARIANT !== "preview") return config;
  return {
    ...config,
    name: "LGU Convocation",
    extra: {
      ...config.extra,
      apiBaseUrl: "https://lguconvocationpk.pythonanywhere.com",
    },
    android: {
      ...config.android,
      package: "pk.edu.lgu.smartconvocation.preview",
      usesCleartextTraffic: false,
    },
  };
};
