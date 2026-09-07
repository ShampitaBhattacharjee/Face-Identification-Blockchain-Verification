# Screen-recording script (unedited, end to end)

Target length: 3 to 5 minutes. Record one continuous take. Keep the terminal large (font 16+) and the browser
visible in a second window. Do not cut; if something fails, keep going and re-run in the same take.

## Before you press record

- [ ] `.env` filled in (SERPAPI_KEY, PRIVATE_KEY) and wallet funded (check balance on the explorer)
- [ ] `python scripts/deploy.py` already run **or** plan to run it on camera (adds ~30 s, looks great)
- [ ] `samples/photo.jpg` is a photo of **you** that you have posted publicly (profile picture is ideal)
- [ ] Ran `python main.py --image samples/photo.jpg --skip-chain` once to confirm a social match appears
- [ ] Browser tab open on `https://amoy.polygonscan.com/address/<your wallet>` (or contract address)
- [ ] Terminal in the repo root with the venv activated, `clear` executed

## Take

| Time | Action | Say / show |
|---|---|---|
| 0:00 | `git log --oneline -3` and `ls` | "This is the repo; everything runs from `main.py`." |
| 0:15 | `cat .env.example` then `ls -la .env` | Show that keys live in `.env` **without** printing its contents. |
| 0:30 | `python scripts/deploy.py` | Contract compiles and deploys; point at the address + explorer link in the green panel. Click the deploy tx in the browser. |
| 1:15 | `python main.py --image samples/photo.jpg` | Stage 1: face box, encoder, two hashes. Stage 2: the matches table appears from the **live** API; highlight the green social-post rows. Stage 3: wallet balance, then tx hash and record id. |
| 2:30 | Click the explorer link from the final panel | Show status *Success*, the `MatchRecorded` event under *Logs*, and the input data. |
| 3:00 | `python scripts/verify.py --record-id 0 --image samples/photo.jpg` | Record read back from chain, `TAMPER-EVIDENCE CHECK PASSED`. |
| 3:20 | Edit the image: `python -c "from PIL import Image; im=Image.open('samples/photo.jpg'); im.putpixel((0,0),(0,0,0)); im.save('samples/photo_edited.jpg')"` then `python scripts/verify.py --record-id 0 --image samples/photo_edited.jpg` | `TAMPER-EVIDENCE CHECK FAILED` on the edited file. This is the money shot for tamper-evidence. |
| 3:50 | `cat output/report_*.json \| head -40` | Show the machine-readable report with the same tx hash. |
| 4:10 | Stop recording | |

## Fallbacks during the take

- **No social match found (exit 3):** re-run with `--use-crop`, or with a different public photo. Say out loud that
  the pipeline refuses to anchor without a real match; that is a feature.
- **RPC timeout:** re-run; or set `RPC_URL` to an Alchemy Amoy endpoint beforehand.
- **Contract not deployed:** the pipeline falls back to calldata mode automatically. Verify with
  `python scripts/verify.py --tx <hash> --image samples/photo.jpg` instead.

## Upload

Upload the raw file (no trimming). Put the link, the tx hash, the contract address and the record id in the
submission form and in the MR/README of your GitHub mirror.
