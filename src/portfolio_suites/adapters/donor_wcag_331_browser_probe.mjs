import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const requireFromRuntime = createRequire(path.join(process.cwd(), 'package.json'));
const { chromium } = requireFromRuntime('playwright');

const source = JSON.parse(fs.readFileSync(0, 'utf8'));
if (source.rule_id !== 'input-assistance-error-msg' || source.wcag_criterion !== '3.3.1') {
  throw new Error('Unexpected donor rule metadata');
}

const cases = [
  { case_id: 'invalid_input_missing_error_ref', element_id: 'email' },
  { case_id: 'invalid_input_with_valid_errormessage', element_id: 'pwd' },
  { case_id: 'invalid_input_with_valid_describedby', element_id: 'name' },
];

const html = `
  <input id="email" type="email" class="is-invalid" aria-invalid="true">
  <input id="pwd" type="password" aria-invalid="true" aria-errormessage="pwd-err">
  <span id="pwd-err">Password must be at least 12 characters.</span>
  <input id="name" type="text" aria-invalid="true" aria-describedby="name-desc">
  <span id="name-desc">Name is required.</span>
`;

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.setContent(html);
  const violations = await page.evaluate(`(${source.evaluate_expression})()`);
  if (!Array.isArray(violations)) {
    throw new Error('Donor rule did not return a violation array');
  }

  const outcomes = Object.fromEntries(
    cases.map(({ case_id, element_id }) => [
      case_id,
      violations.some(({ element = '' }) => (
        element.includes(`id="${element_id}"`) || element.includes(`id='${element_id}'`)
      )),
    ]),
  );

  process.stdout.write(JSON.stringify({
    rule_id: source.rule_id,
    wcag_criterion: source.wcag_criterion,
    cases,
    outcomes,
    violations,
  }));
} finally {
  await browser.close();
}
