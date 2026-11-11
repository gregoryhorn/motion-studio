// Dashboard SDK only; deliberately no native host transport or record access.
(()=>{const sdk=window.__HERMES_PLUGIN_SDK__;
  if(!window.__HERMES_PLUGINS__?.register||!sdk?.React)return;
  window.__HERMES_PLUGINS__.register('motion-studio',()=>sdk.React.createElement('p',null,
    'Motion Studio status only. Open the separate native Desktop route for public technical proposals. Access/inference are unconfigured; private media and native creation/playback/save remain unavailable.'));
})();
