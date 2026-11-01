from finagent.recon.jobs.sec_companyfacts import SecCompanyFacts
from finagent.recon.jobs.sec_frames import SecFrames
from finagent.recon.jobs.sec_submissions import SecSubmissions
from finagent.recon.jobs.sec_tickers import SecTickers

# name -> factory(settings); listed in dependency order.
REGISTRY = {
    "sec_tickers": lambda s: SecTickers(),
    "sec_frames": lambda s: SecFrames(),
    "sec_submissions": lambda s: SecSubmissions(s.slice_file),
    "sec_companyfacts": lambda s: SecCompanyFacts(s.slice_file),
}
