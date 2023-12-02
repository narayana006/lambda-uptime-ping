# lambda-uptime-ping

A tiny scheduled AWS Lambda that checks your URLs and posts to Slack when one is down or slow.

> **Project status: planning. There is no working code in this repository yet.**
> This README describes what the project will do. Nothing below can be installed or run today.
> Features are ticked off in the checklist as they are built.

## What it is

A deployable serverless application.

**The problem it solves:** Small projects need basic uptime checks without paying for or running a monitoring service.

## Who it is for

People with a few sites or APIs who want simple alerts.

## How it will work

1. You list your URLs in a config file.
2. You deploy the function with one command.
3. It checks the URLs every few minutes and messages you when something changes.

## Planned features

Unticked items are not built yet.

- [ ] Checks a list of URLs on a schedule
- [ ] Alerts on failures, slow responses and expiring TLS certificates
- [ ] Alerts once and again on recovery, not every run
- [ ] One-command deploy with AWS SAM
- [ ] Runs within the Lambda free tier for typical use

## Planned usage

This is the intended interface, shown so you can judge the design. **It does not work yet**, and names may change before the first release.

```bash
sam deploy --guided
```

## Contributing

Feedback on the design is the most useful contribution right now. Open an issue to suggest a feature, question an approach or describe your use case. Code contributions are welcome once the first version lands.

## Author

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
