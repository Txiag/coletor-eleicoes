import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium, expect } = require('@playwright/test');
const base = process.env.DASHBOARD_URL || 'http://127.0.0.1:5173';
const output = resolve(process.env.DASHBOARD_SCREENSHOTS || 'docs/implementation/screenshots');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const exceptions = [], checks = [], requests = [];
page.on('pageerror', error => exceptions.push(error.message));
const record = name => { checks.push(name); console.log(`PASS ${name}`); };
const collected = '2026-10-04T20:00:00Z';
const label = 'Demonstração de teste — dados sintéticos EA20';
const parties = [{ number: '90', name: 'Teste Alfa' }, { number: '91', name: 'Teste Beta' }];
const metadata = {
  datasets: [{ id: 'teste', name: label, phase: 'Teste', elections: [
    { code: 'f1', round: 1, offices: [{ code: '1', name: 'Presidente', scopes: ['br'] }] },
    { code: 'e1', round: 1, offices: [{ code: '3', name: 'Governador', scopes: ['ac', 'ce'] }] },
    { code: 'f2', round: 2, offices: [{ code: '1', name: 'Presidente', scopes: ['br'] }] },
  ] }], parties, refresh_seconds: 30, stale_seconds: 300,
};
const shape = (id, name, uf, x) => ({ type: 'Feature', properties: { id, name, uf },
  geometry: { type: 'Polygon', coordinates: [[[x, -7], [x + 2, -7], [x + 2, -4], [x, -4], [x, -7]]] } });
const source = () => ({ kind: 'official', label, available: true, reason: null, error: null,
  updated_at: new Date().toISOString(), collected_at: new Date().toISOString(), checked_at: new Date().toISOString(),
  url: null, official_progress: 75, totalized_sections: 75, total_sections: 100 });
const territory = (id, name, level, margin = 10) => ({ id, name, level, votes: 1000, candidate_votes: null, state: 'available', margin,
  leader: { number: '90', name: parties[0].name, votes: 500 + margin * 5 },
  runner_up: { number: '91', name: parties[1].name, votes: 500 - margin * 5 }, source: source() });
const territories = params => params.has('zone') ? { level: 'zone', limited: false, items: [] }
  : params.has('municipality') ? { level: 'zone', limited: false, items: [territory('0001', 'Zona 0001', 'zone')] }
  : params.has('uf') ? { level: 'municipality', limited: false, items: [territory(params.get('uf') === 'ce' ? '13897' : '01074', params.get('uf') === 'ce' ? 'Fortaleza de teste' : 'Cidade do Acre de teste', 'municipality', params.get('uf') === 'ce' ? 80 : 10)] }
  : { level: 'uf', limited: false, items: [territory('ac', 'Acre', 'uf'), territory('ce', 'Ceará', 'uf', 80)] };

// Todas as rotas de dados são interceptadas: o teste não consulta nem modifica um banco eleitoral.
let failDashboard = false;
await page.route('**/api/**', async route => {
  const url = new URL(route.request().url()), params = url.searchParams;
  requests.push(url);
  let json;
  switch (url.pathname) {
    case '/api/metadata': json = metadata; break;
    case '/api/geography': {
      const uf = params.get('uf');
      json = { available: true, reason: null, attribution: label, edition: 'Teste', features: uf
        ? [shape(uf === 'ce' ? '13897' : '01074', uf === 'ce' ? 'Fortaleza de teste' : 'Cidade do Acre de teste', uf, uf === 'ce' ? -40 : -70)]
        : [shape('ac', 'Acre', 'ac', -70), shape('ce', 'Ceará', 'ce', -40)] };
      break;
    }
    case '/api/options': json = { items: [{ value: '13897', label: 'Fortaleza de teste' }], total: 1, page: 1, page_size: 30 }; break;
    case '/api/map': json = { territories: territories(params) }; break;
    case '/api/dashboard': {
      if (failDashboard) return route.fulfill({ status: 503, json: { detail: 'Falha de comunicação simulada no teste de interface.' } });
      const place = params.has('zone') ? 'Zona' : params.has('municipality') ? 'Municipal' : params.has('uf') ? 'Estadual' : 'Nacional';
      const items = Array.from({ length: 5 }, (_, i) => ({ number: String(90 + i), scope: 'br', name: `Candidatura ${place} ${i + 1} de teste`, party: i % 2 ? '91' : '90', party_name: parties[i % 2].name, votes: 300 - i * 50, percentage: 30 - i * 5 }));
      json = { queried_at: new Date().toISOString(), source: source(),
        summary: { votes: 1000, nominal_votes: 1000, categories: [{ type: 'nominal', votes: 1000 }] }, parties,
        candidates: { items, total: 5, page: 1, page_size: 5, denominator: 1000, denominator_label: 'votos nominais' },
        territories: territories(params), regions: [{ id: 'norte', name: 'Norte', total: 100, totalized: 75, percentage: 75, status: 'available',
          expected_ufs: ['ac'], missing_ufs: [], error_ufs: [], updated_at: collected, collected_at: collected,
          ranking: { status: 'available', items: items.slice(0, 2) } }] };
      break;
    }
    default: throw new Error(`Rota sem fixture: ${url.pathname}`);
  }
  await route.fulfill({ json });
});
const dashboardResponse = (key, value) => page.waitForResponse(response => {
  const url = new URL(response.url());
  return url.pathname === '/api/dashboard' && url.searchParams.get(key) === value && response.ok();
});
try {
  await page.goto(base);
  await expect(page.locator('#resultados .ranking li')).toHaveCount(5);
  await expect(page.locator('[data-key="uf::ce"]')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Presidente', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.screenshot({ path: resolve(output, 'desktop.png'), fullPage: true });
  record('EA20 sintético: mapa, ranking nacional e apuração regional');

  await Promise.all([dashboardResponse('office', '3'), page.getByRole('button', { name: 'Governador', exact: true }).click()]);
  await expect.poll(() => new URL(page.url()).pathname).toBe('/uf/ac');
  await expect(page.getByRole('button', { name: 'Governador', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.locator('.round-select select').selectOption('2');
  await expect(page.getByRole('button', { name: 'Presidente', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.locator('.round-select select').selectOption('1');
  record('Cargo e turno resolvem eleição e circunscrição compatível');

  await page.getByText('Buscar município', { exact: true }).click();
  await page.getByRole('searchbox').fill('Fortaleza');
  await Promise.all([dashboardResponse('municipality', '13897'), page.getByRole('button', { name: /^Fortaleza de teste:/ }).click()]);
  await expect(page.getByRole('dialog')).toContainText('Candidatura Municipal 1 de teste');
  await expect(page.locator('#resultados')).toContainText('Candidatura Nacional 1 de teste');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.goto(`${base}/uf/ce/municipio/13897?dataset=teste&election=f1&office=1&zone=0001&source=official&at=2026-10-04T20%3A00%3A00Z`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Zona 0001');
  await expect(page.getByRole('dialog')).toContainText('Candidatura Zona 1 de teste');
  await expect.poll(() => new URL(page.url()).searchParams.has('at')).toBe(false);
  await page.getByRole('button', { name: 'CE', exact: true }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/uf/ce');
  await page.goBack();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Zona 0001');
  record('Município e zona preservam ranking nacional, link e histórico territorial');

  await page.goto(base);
  await expect(page.locator('#resultados .ranking li')).toHaveCount(5);
  await page.getByText('Personalizar cores dos partidos', { exact: true }).click();
  const color = page.getByLabel('Hexadecimal de Teste Alfa', { exact: true });
  const canvas = page.locator('canvas');
  const beforeColor = await canvas.evaluate(el => el.toDataURL());
  await color.fill('#193ddd');
  await color.blur();
  await expect.poll(() => canvas.evaluate(el => el.toDataURL())).not.toBe(beforeColor);
  await page.reload();
  await page.getByText('Personalizar cores dos partidos', { exact: true }).click();
  await expect(color).toHaveValue('#193ddd');
  await page.getByRole('button', { name: 'Restaurar paleta', exact: true }).click();
  record('Cor partidária altera o canvas, persiste e pode ser restaurada');

  await page.getByRole('button', { name: 'Pausar', exact: true }).click();
  const before = await page.locator('#resultados').innerText();
  failDashboard = true;
  await page.getByRole('button', { name: /Atualizar agora/ }).click();
  await expect(page.getByText('Falha na atualização', { exact: true })).toBeVisible();
  await expect(page.locator('#resultados')).toHaveText(before, { useInnerText: true });
  failDashboard = false;
  await page.getByRole('button', { name: /Atualizar agora/ }).click();
  await expect(page.getByText('Consulta atualizada', { exact: true })).toBeVisible();
  record('Falha preserva ranking e atualização manual recupera');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve(output, 'mobile.png'), fullPage: true });
  await page.screenshot({ path: resolve(output, 'mobile-top.png') });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: 'Presidente', exact: true })).toBeVisible();
  record('Viewport móvel 390×844 mantém navegação sem transbordamento');
  expect(exceptions).toEqual([]);
  record('Sem exceções JavaScript');
  await writeFile(resolve(output, 'checks.json'), JSON.stringify({ base, fixture: label, checks, exceptions, checked_at: new Date().toISOString() }, null, 2), 'utf8');
} catch (error) {
  console.error('Elementos além da viewport:', await page.evaluate(() => [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth + 1).slice(0, 15).map(el => ({ tag: el.tagName, className: el.className, right: el.getBoundingClientRect().right }))));
  console.error('Últimas consultas:', requests.slice(-8).map(url => url.pathname + url.search));
  throw error;
} finally {
  await browser.close();
}
