# lambda-uptime-ping

A tiny scheduled AWS Lambda that checks your URLs and posts to Slack when one is down, slow, or about to have its TLS certificate expire. It alerts when a status changes, not on every run.

**Status:** the checker, the alert-on-change logic, the Lambda handler and a local `--once` command all work and are covered by tests. The SAM template is written and passes `cfn-lint`, but **it has not been deployed to a real AWS account yet**, so treat the deploy steps as untested until someone confirms them.

## Try it without AWS

The same checks the Lambda runs can be run once from your terminal. Nothing here needs an AWS account or credentials.

```bash
git clone https://github.com/narayana006/lambda-uptime-ping
cd lambda-uptime-ping
pip install -e .
uptime-ping --once --config examples/config.json
```

Real output from that command (it makes two GET requests to `https://example.com`; your timings will differ):

```text
STATUS  NAME            HTTP  TIME    DETAIL
ok      example         200   128 ms  HTTP 200 in 128 ms, TLS certificate valid for 45 more days
ok      example-strict  200   129 ms  HTTP 200 in 129 ms, TLS certificate valid for 45 more days

No status changes, nothing to alert on.
```

To see failures, start the bundled demo server in one terminal and check it from another, keeping state in a file:

```bash
python examples/demo_server.py          # serves http://127.0.0.1:8808
uptime-ping --once --config examples/config.local.json --state-file /tmp/uptime-state.json
```

First run (real output, exit code 1 because something is unhealthy):

```text
STATUS  NAME         HTTP  TIME    DETAIL
ok      home         200   6 ms    HTTP 200 in 6 ms
slow    reports      200   815 ms  HTTP 200 in 815 ms, slower than the 500 ms threshold
down    billing-api  503   6 ms    HTTP 503, expected 2xx or 3xx
ok      login        302   6 ms    HTTP 302 in 6 ms

Alerts (not sent, --notify is off):
  [SLOW] reports (http://127.0.0.1:8808/slow): HTTP 200 in 815 ms, slower than the 500 ms threshold
  [DOWN] billing-api (http://127.0.0.1:8808/broken): HTTP 503, expected 2xx or 3xx
```

Run the same command again and the table is the same but the last part becomes:

```text
No status changes, nothing to alert on.
```

Stop the demo server and run it a third time:

```text
STATUS  NAME         HTTP  TIME  DETAIL
down    home         -     -     [Errno 61] Connection refused
down    reports      -     -     [Errno 61] Connection refused
down    billing-api  -     -     [Errno 61] Connection refused
down    login        -     -     [Errno 61] Connection refused

Alerts (not sent, --notify is off):
  [DOWN] home (http://127.0.0.1:8808/): [Errno 61] Connection refused (was ok)
  [DOWN] reports (http://127.0.0.1:8808/slow): [Errno 61] Connection refused (was slow)
  [DOWN] login (http://127.0.0.1:8808/redirect): [Errno 61] Connection refused (was ok)
```

`billing-api` was already down, so it is not reported again.

If you only want the command and not the examples: `pip install git+https://github.com/narayana006/lambda-uptime-ping`.

### CLI options

```text
uptime-ping --once --config FILE [--state-file FILE] [--notify] [--json]
```

| Option | Meaning |
| --- | --- |
| `--once` | Run all checks one time and exit. Required; there is no local loop mode. |
| `--config FILE` | The JSON config file (format below). |
| `--state-file FILE` | Remember each target's status in this file so repeat runs only report changes. Without it, every unhealthy target is reported every time. |
| `--notify` | Also post the alerts to the Slack webhook in `$SLACK_WEBHOOK_URL`. Off by default. |
| `--json` | Print the full run summary as JSON instead of the table. |

Exit codes: `0` all targets healthy, `1` at least one unhealthy, `2` bad arguments or config, `3` an alert could not be delivered to Slack.

## Config file

```json
{
  "defaults": {
    "timeout_seconds": 10,
    "slow_ms": 2000,
    "cert_warn_days": 14
  },
  "targets": [
    { "name": "example", "url": "https://example.com" },
    { "name": "example-strict", "url": "https://example.com/", "expect_status": 200, "slow_ms": 5000 }
  ]
}
```

- A target is an object or just a URL string. Only `http://` and `https://` URLs are accepted.
- `name` defaults to the URL and must be unique. State is stored under the name, so renaming a target resets its history.
- `expect_status`: one status code or a list. If omitted, any 2xx or 3xx counts as healthy. Redirects are not followed; a 302 is simply a 302.
- `slow_ms`: a response slower than this is `slow`. The time covers connect, TLS handshake and response headers, not the body.
- `cert_warn_days`: for `https://` targets, warn when the certificate has fewer than this many days left.
- `timeout_seconds` applies to each socket operation (connect, send, read), so one check can take somewhat longer than this in the worst case.
- Anything set on a target overrides `defaults`. The values shown above are the built-in defaults. Unknown keys are rejected so typos do not pass silently.

## How statuses and alerts work

Each run gives every target exactly one status. If several problems apply, the first in this list wins:

| Status | When |
| --- | --- |
| `down` | No response (DNS failure, refused connection, timeout, TLS error such as an already expired certificate) or an unexpected status code |
| `slow` | Responded correctly but slower than `slow_ms` |
| `cert_expiring` | Fine, but the certificate expires within `cert_warn_days` |
| `ok` | None of the above |

The last status of each target is stored (DynamoDB in Lambda, the `--state-file` locally). An alert is sent only when the new status differs from the stored one:

- unchanged status: nothing is sent;
- a target seen for the first time: an alert only if it is unhealthy;
- any other change, including back to `ok` (`[RECOVERED]`): one alert.

If posting to Slack fails, the new status is not stored, so the next run tries the same alert again, and the Lambda invocation ends with an error so it shows in the function's `Errors` metric.

## Running the Lambda handler locally

`examples/invoke_local.py` calls the real handler four times with a scheduled-event payload. DynamoDB is [moto](https://github.com/getmoto/moto)'s in-memory mock, Slack is replaced by a function that prints the payload, and the HTTP checks are real requests to the demo server started in-process on `127.0.0.1:8808`. No AWS account is involved.

```bash
pip install -e ".[dev]"
python examples/invoke_local.py
```

Real output:

```text
== run 1: first run, two targets are unhealthy
  slack <- {"text": "[SLOW] reports (http://127.0.0.1:8808/slow): HTTP 200 in 807 ms, slower than the 500 ms threshold"}
  slack <- {"text": "[DOWN] billing-api (http://127.0.0.1:8808/broken): HTTP 503, expected 2xx or 3xx"}
  checked 4, unhealthy 2, alerts 2
  home=ok, reports=slow, billing-api=down, login=ok

== run 2: nothing changed, so no alerts
  checked 4, unhealthy 2, alerts 0
  home=ok, reports=slow, billing-api=down, login=ok

== run 3: the whole site starts answering 503
  slack <- {"text": "[DOWN] home (http://127.0.0.1:8808/): HTTP 503, expected 2xx or 3xx (was ok)"}
  slack <- {"text": "[DOWN] reports (http://127.0.0.1:8808/slow): HTTP 503, expected 2xx or 3xx (was slow)"}
  slack <- {"text": "[DOWN] login (http://127.0.0.1:8808/redirect): HTTP 503, expected 301 or 302 (was ok)"}
  checked 4, unhealthy 4, alerts 3
  home=down, reports=down, billing-api=down, login=down

== run 4: the outage is over
  slack <- {"text": "[RECOVERED] home (http://127.0.0.1:8808/): HTTP 200 in 1 ms (was down)"}
  slack <- {"text": "[SLOW] reports (http://127.0.0.1:8808/slow): HTTP 200 in 802 ms, slower than the 500 ms threshold (was down)"}
  slack <- {"text": "[RECOVERED] login (http://127.0.0.1:8808/redirect): HTTP 302 in 2 ms (was down)"}
  checked 4, unhealthy 2, alerts 3
  home=ok, reports=slow, billing-api=down, login=ok

== state table after run 4
  billing-api: down
  home: ok
  login: ok
  reports: slow
```

## Deploying with AWS SAM

> The template passes `cfn-lint` and the tests check that it matches the code (handler path, table key, IAM actions). It has not been deployed by the author, and `sam validate` / `sam build` have not been run against it. Please open an issue if a step below does not work.

1. Edit `src/config.json` with your URLs. It is packaged with the function.
2. Deploy with the [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html):

   ```bash
   sam build && sam deploy --guided
   ```

   You will be asked for two parameters:

   | Parameter | Default | Meaning |
   | --- | --- | --- |
   | `SlackWebhookUrl` | empty | A Slack incoming webhook URL. If empty, alerts are only written to the function's log as `ALERT ...` lines. |
   | `ScheduleExpression` | `rate(5 minutes)` | An EventBridge `rate()` or `cron()` expression. |

3. To change the URLs later, edit `src/config.json` and deploy again. To remove everything, `sam delete` (this also deletes the state table).

What the template creates:

- one Lambda function (Python 3.12, arm64, 128 MB, 60 s timeout), not attached to a VPC, so it can only check URLs reachable from the public internet;
- one EventBridge schedule rule that invokes it;
- one DynamoDB table (on-demand billing, partition key `target`) holding one small item per target.

### IAM permissions of the function

The function's role is allowed exactly these actions on the state table and nothing else in DynamoDB:

- `dynamodb:GetItem`
- `dynamodb:PutItem`

SAM also attaches the AWS managed policy `AWSLambdaBasicExecutionRole` so the function can write its logs. Each run does one `GetItem` per target, and a `PutItem` only when a status changed.

### Cost

No cost figures are given here because none have been measured. The moving parts that are billed are Lambda invocations and duration (one invocation per schedule tick, 8,640 a month at the default 5 minutes), DynamoDB on-demand requests, and CloudWatch Logs storage for one JSON line per run. Check those against current AWS pricing and your account's free tier.

### Things to know

- The Slack webhook URL is stored as a plain Lambda environment variable. Anyone who can read the function's configuration can read it. `NoEcho` only hides it in CloudFormation output.
- Each run prints a JSON summary of every check to the log, including the URLs.

## Feature checklist

- [x] Checks a list of URLs from a config file (concurrently, standard library only)
- [x] Alerts on failures, slow responses and expiring TLS certificates
- [x] Alerts once and again on recovery, not every run
- [x] Local `--once` command that needs no AWS account
- [ ] One-command deploy with AWS SAM (template written and linted, not yet verified by a real deployment)
- [ ] Runs within the Lambda free tier for typical use (not measured, so not claimed)
- [ ] Require N consecutive failures before alerting
- [ ] Notification targets other than Slack

## Limitations

- One failed check is enough to alert. There is no "N failures in a row" setting yet, so a single network blip produces a DOWN and then a RECOVERED message.
- Checks run from a single AWS region, so a regional network problem looks like your site being down.
- GET requests only, no custom headers, no request body, no checking of the response body.
- Redirects are not followed.
- The certificate check only looks at the expiry date of the certificate the server presents. An already expired or otherwise invalid certificate shows up as `down`, not `cert_expiring`.
- If the function itself stops running (deleted schedule, account problem), nothing tells you. It does not monitor itself.
- Slack is the only notification channel.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The tests never touch the network beyond the loopback interface and never touch AWS: HTTP checks use an injected fake `fetch` function (plus a throwaway server on `127.0.0.1` for the real one), DynamoDB is mocked with moto, and `tests/conftest.py` sets dummy AWS credentials.

Layout:

```text
src/config.json            URLs checked by the deployed function
src/uptime_ping/checks.py  the HTTP check and status classification
src/uptime_ping/monitor.py one run: check, compare with stored status, alert
src/uptime_ping/state.py   memory, file and DynamoDB state stores
src/uptime_ping/notify.py  alert text and Slack delivery
src/uptime_ping/handler.py Lambda entry point
src/uptime_ping/cli.py     the local uptime-ping command
template.yaml              SAM template
```

## Contributing

Issues and pull requests are welcome. The most useful thing right now is a report from a real `sam deploy`: what worked and what did not. For code changes, please add a test and keep the checker free of third-party dependencies.

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
