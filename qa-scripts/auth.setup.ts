import { test as setup } from '@playwright/test';
import * as path from 'path';

// One-time login. Run with:  npx playwright test --project=setup
// It signs in with QA_USERNAME / QA_PASSWORD (from qa-scripts/.env) and saves
// the browser session to .auth/state.json — after that every *.spec.ts starts
// already authenticated (see storageState in playwright.config.ts).
//
// The locators below cover common login forms; ADJUST them to match your app.
const authFile = path.join(__dirname, '.auth', 'state.json');

setup('authenticate', async ({ page }) => {
  const url = process.env.QA_LOGIN_URL || process.env.QA_BASE_URL;
  if (!url) throw new Error('Set QA_BASE_URL (or QA_LOGIN_URL) in qa-scripts/.env');
  if (!process.env.QA_PASSWORD) throw new Error('Set QA_PASSWORD in qa-scripts/.env');

  await page.goto(url);

  // TODO: adjust to your login form if these do not match.
  await page.getByLabel(/e-?mail|correo|user|usuario/i).first()
    .fill(process.env.QA_USERNAME ?? '');
  await page.getByLabel(/password|contrase/i).first()
    .fill(process.env.QA_PASSWORD ?? '');
  await page.getByRole('button', { name: /sign ?in|log ?in|entrar|iniciar/i }).first()
    .click();

  // Give the app a moment to establish the session, then persist it.
  await page.waitForLoadState('networkidle');
  await page.context().storageState({ path: authFile });
});
