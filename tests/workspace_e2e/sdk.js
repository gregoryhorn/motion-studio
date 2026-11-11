// Existing supported offline SDK facade, exposed only to the qualification harness.
export * from '../native-sdk-browser.js';
import {host} from '../native-sdk-browser.js';
window.workspaceHost = host;
