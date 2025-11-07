# MDK Python Example

CLI app showing how Marmot Development Kit works in a python application. Not meant to be a real world application of course.

## Get it running

First build the UniFFI bindings (you need this or nothing works):
```bash
cargo build -p mdk-uniffi
```

Then grab the Python deps:
```bash
uv pip install -r requirements.txt
```

## Setup

Toss your private key in an env variable:
```bash
export PRIVATE_KEY=your_hex_encoded_private_key
```

## Running it

Just do:
```bash
uv python main.py
```

## What you can do

**1. Generate key package** - Makes a key package and pushes it to relays (you need this before joining groups, otherwise you're invisible to the MLS protocol)

**2. Create group** - Start a new group with other people

**3. View pending invites** - Check invites you've got waiting

**4. Invite to group** - Add someone to a group you're in

**5. Send message to group** - Send a message to whichever group you pick

**6. Publish metadata** - Push your profile and relay list info

**7. Exit** - Get out and touch grass

## Quick notes

Default relays are `wss://relay.damus.io` and `wss://relay.arx-ccn.com`.