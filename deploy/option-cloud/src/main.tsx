import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { DecisionDeskApp } from './decisionDesk/DecisionDeskApp';
import './base.css';
import './preview.css';
const root = document.getElementById('root');
if (!root) throw new Error('preview root missing');
createRoot(root).render(<StrictMode><DecisionDeskApp /></StrictMode>);
