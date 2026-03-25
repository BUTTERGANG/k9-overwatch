{ pkgs }:
{
  deps = [
    pkgs.python312
    pkgs.chromium
    pkgs.nodejs_20
    pkgs.postgresql_15
  ];
  env = {
    PLAYWRIGHT_BROWSERS_PATH = "/nix/store";
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1";
    # Set CHROMIUM_PATH to the Nix chromium binary for Playwright scrapers:
    # CHROMIUM_PATH = "${pkgs.chromium}/bin/chromium";
  };
}
