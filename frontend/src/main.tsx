import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import BuiltWithBadge from './BuiltWithBadge';
import './error-reporter'; // Builder-internal: forwards runtime errors to the App Builder popup
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
    {/* Builder-internal: "Built with Understand Tech" attribution.
        Rendered as a sibling of <App /> so it's visible on every
        route regardless of how the agent structures the app. */}
    <BuiltWithBadge />
  </StrictMode>,
);
