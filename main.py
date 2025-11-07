import asyncio
import json
import os
import sys
from pathlib import Path
from nostr_sdk import Client, Event, Keys, PublicKey, EventBuilder, NostrSigner, Kind, Filter, RelayUrl, Tag, UnsignedEvent
from nostr_sdk.nostr_sdk import Duration, Timestamp

bindings_dir = Path(__file__).parent.parent.parent / "bindings" / "python"
sys.path.insert(0, str(bindings_dir))

try:
    from mdk_uniffi import new_mdk
except ImportError:
    print("Error: Could not import mdk_uniffi. Make sure the bindings are built.")
    print(f"Expected bindings at: {bindings_dir}")
    sys.exit(1)

class MdkExampleApp:
    def __init__(self, db_path: str, keys: Keys, relays: list[str]):
        self.keys = keys
        self.signer = NostrSigner.keys(keys)
        self.relays = relays
        self.mdk = new_mdk(db_path)
        self.client = None

    async def init_client(self):
        self.client = Client(self.signer)
        
        for relay_url in self.relays:
            try:
                await self.client.add_relay(RelayUrl.parse(relay_url))
            except Exception:
                pass
        
        await self.client.connect()

    async def close(self):
        if self.client:
            await self.client.disconnect()

    async def generate_keypackage(self):
        result = self.mdk.create_key_package_for_event(
            self.keys.public_key().to_hex(),
            self.relays
        )
        event_builder = EventBuilder(Kind(443), result.key_package)
        tags = [Tag.parse(tag) for tag in result.tags] + [Tag.client("mdk-python-example")]
        await self.client.send_event_builder(event_builder.tags(tags))

    async def fetch_keypackage(self, npub: str) -> Event | None:
        pubkey = PublicKey.parse(npub)
        filter = Filter().kind(Kind(443)).author(pubkey).limit(1)
        events = await self.client.fetch_events(filter, Duration(seconds=10))
            
        if events:
            return events.first() 
        return None

    async def publish_welcome_rumors(self, welcome_rumors_json: list[str], member_npubs: list[str], member_key_package_events: list[Event]):
        if not welcome_rumors_json:
            return
        
        event_id_to_npub = {kp.id(): npub for npub, kp in zip(member_npubs, member_key_package_events) if kp.id()}
        expiration = Timestamp.now().add_duration(Duration(seconds=30 * 24 * 60 * 60))
        member_relays = [RelayUrl.parse(url) for url in self.relays]

        for welcome_rumor_json in welcome_rumors_json:
            try:
                welcome_rumor = json.loads(welcome_rumor_json)
                event_id = next((tag[1] for tag in welcome_rumor.get('tags', []) if len(tag) >= 2 and tag[0] == 'e'), None)
                if not event_id or event_id not in event_id_to_npub:
                    continue
                
                member_pubkey = PublicKey.parse(event_id_to_npub[event_id])
                unsigned_event = UnsignedEvent.from_json(welcome_rumor_json)
                await self.client.gift_wrap_to(member_relays, member_pubkey, unsigned_event, [Tag.expiration(expiration)])
            except Exception as e:
                print(f"Error: {e}")

    async def create_group(self, name: str, description: str, member_npubs: list[str]):
        if not member_npubs:
            print("Error: At least one member npub is required")
            return
        
        member_key_package_events = []
        member_key_package_events_dict = []
        for npub in member_npubs:
            kp = await self.fetch_keypackage(npub)
            if not kp:
                print(f"Error: Could not find key package for {npub}")
                return
            member_key_package_events.append(kp.as_json())
            member_key_package_events_dict.append(kp)
        
        result = self.mdk.create_group(
            creator_public_key=self.keys.public_key().to_hex(),
            member_key_package_events_json=member_key_package_events,
            name=name,
            description=description,
            relays=self.relays,
            admins=[self.keys.public_key().to_hex()]
        )

        if result.welcome_rumors_json:
            await self.publish_welcome_rumors(result.welcome_rumors_json, member_npubs, member_key_package_events_dict)

    async def invite_member(self, group_id: str, member_npub: str):
        kp = await self.fetch_keypackage(member_npub)
        if not kp:
            return
        
        result = self.mdk.add_members(mls_group_id=group_id, key_package_events_json=[json.dumps(kp)])
        if result.welcome_rumors_json:
            await self.publish_welcome_rumors(result.welcome_rumors_json, [member_npub], [kp])

    def accept_welcome(self, welcome):
        welcome_json = json.dumps({
            "id": welcome.id,
            "event_json": welcome.event_json,
            "mls_group_id": welcome.mls_group_id,
            "nostr_group_id": welcome.nostr_group_id,
            "group_name": welcome.group_name,
            "group_description": welcome.group_description,
            "group_admin_pubkeys": welcome.group_admin_pubkeys,
            "group_relays": welcome.group_relays,
            "welcomer": welcome.welcomer,
            "member_count": welcome.member_count,
            "state": welcome.state,
            "wrapper_event_id": welcome.wrapper_event_id
        })
        self.mdk.accept_welcome(welcome_json)

    def send_message(self, group_id: str, content: str) -> dict | None:
        try:
            event_json = self.mdk.create_message(
                mls_group_id=group_id,
                sender_public_key=self.keys.public_key().to_hex(),
                content=content,
                kind=1
            )
            return json.loads(event_json)
        except Exception as e:
            print(f"Error: {e}")
            return None

    async def publish_message(self, event_json: dict):
        await self.client.send_event(Event.from_json(json.dumps(event_json)))

    def view_pending_invites(self):
        welcomes = self.mdk.get_pending_welcomes()
        for i, welcome in enumerate(welcomes, 1):
            print(f"{i}. {welcome.group_name} - {welcome.welcomer}")
        return welcomes

    def select_group(self):
        groups = self.mdk.get_groups()
        if not groups:
            return None
        
        for i, group in enumerate(groups, 1):
            print(f"{i}. {group.name}")
        
        while True:
            try:
                choice = input("Enter group number (or 'q' to cancel): ").strip()
                if choice.lower() == 'q':
                    return None
                idx = int(choice) - 1
                if 0 <= idx < len(groups):
                    return groups[idx]
            except (ValueError, KeyboardInterrupt):
                return None

    async def publish_metadata(self, name: str):
        profile_builder = EventBuilder(Kind(0), json.dumps({"name": name}))
        await self.client.send_event_builder(profile_builder)
        
        relay_tags = [Tag.parse(["relay", url]) for url in self.relays]
        for kind in [10002, 10050, 10051]:
            await self.client.send_event_builder(EventBuilder(Kind(kind), "").tags(relay_tags))


def print_menu():
    print("\n" + "=" * 50)
    print("MDK Example App - Main Menu")
    print("=" * 50)
    print("1) Generate key package")
    print("2) Create group")
    print("3) View pending invites")
    print("4) Invite to group")
    print("5) Send message to group")
    print("6) Publish metadata")
    print("7) Exit")
    print("=" * 50)

async def handle_generate_keypackage(app: MdkExampleApp):
    try:
        await app.generate_keypackage()
    except Exception as e:
        print(f"Error: {e}")

async def handle_create_group(app: MdkExampleApp):
    try:
        name = input("Enter group name: ").strip()
        if not name:
            print("Error: Group name cannot be empty")
            return
        
        description = input("Enter group description (optional): ").strip() or ""
        npubs_input = input("Enter member npubs (comma-separated): ").strip()
        
        member_npubs = [npub.strip() for npub in npubs_input.split(",") if npub.strip()]
        if not member_npubs:
            print("Error: At least one member npub is required")
            return
        
        await app.create_group(name, description, member_npubs)
        print(f"Group '{name}' created successfully")
    except (KeyboardInterrupt, Exception) as e:
        if not isinstance(e, KeyboardInterrupt):
            print(f"Error: {e}")

async def handle_view_pending_invites(app: MdkExampleApp):
    try:
        welcomes = app.view_pending_invites()
        if welcomes and input("Accept any invites? (y/n): ").strip().lower() == 'y':
            while True:
                try:
                    choice = input(f"Enter invite number (1-{len(welcomes)}) or 'q': ").strip()
                    if choice.lower() == 'q':
                        break
                    idx = int(choice) - 1
                    if 0 <= idx < len(welcomes):
                        app.accept_welcome(welcomes[idx])
                        print(f"Accepted invite to group: {welcomes[idx].group_name}")
                        break
                except (ValueError, KeyboardInterrupt):
                    break
    except (KeyboardInterrupt, Exception) as e:
        if not isinstance(e, KeyboardInterrupt):
            print(f"Error: {e}")

async def handle_invite_to_group(app: MdkExampleApp):
    try:
        group = app.select_group()
        if not group:
            return
        
        npub = input("Enter npub of member to invite: ").strip()
        if not npub:
            print("Error: npub cannot be empty")
            return
        
        await app.invite_member(group.mls_group_id, npub)
        print(f"Invitation sent to {npub}")
    except (KeyboardInterrupt, Exception) as e:
        if not isinstance(e, KeyboardInterrupt):
            print(f"Error: {e}")

async def handle_send_message(app: MdkExampleApp):
    try:
        group = app.select_group()
        if not group:
            return
        
        content = input("Enter message content: ").strip()
        if not content:
            print("Error: Message content cannot be empty")
            return
        
        message_event = app.send_message(group.mls_group_id, content)
        if message_event:
            await app.publish_message(message_event)
            print(f"Message sent to group '{group.name}'")
    except (KeyboardInterrupt, Exception) as e:
        if not isinstance(e, KeyboardInterrupt):
            print(f"Error: {e}")

async def handle_publish_metadata(app: MdkExampleApp):
    try:
        name = input("Enter your name: ").strip()
        if not name:
            print("Error: Name cannot be empty")
            return
        
        await app.publish_metadata(name)
        print("Metadata published successfully")
    except (KeyboardInterrupt, Exception) as e:
        if not isinstance(e, KeyboardInterrupt):
            print(f"Error: {e}")

async def main():
    private_key_hex = os.getenv("PRIVATE_KEY")
    if not private_key_hex:
        print("Error: PRIVATE_KEY environment variable is required")
        sys.exit(1)
    
    try:
        keys = Keys.parse(private_key_hex)
    except Exception as e:
        print(f"Error loading keys: {e}")
        sys.exit(1)
    
    app = MdkExampleApp("mdk_example.db", keys, ["wss://relay.damus.io", "wss://relay.arx-ccn.com"])
    
    try:
        await app.init_client()
        
        while True:
            print_menu()
            try:
                choice = input("\nEnter your choice (1-7): ").strip()
                
                if choice == "7":
                    break
                elif choice == "1":
                    await handle_generate_keypackage(app)
                elif choice == "2":
                    await handle_create_group(app)
                elif choice == "3":
                    await handle_view_pending_invites(app)
                elif choice == "4":
                    await handle_invite_to_group(app)
                elif choice == "5":
                    await handle_send_message(app)
                elif choice == "6":
                    await handle_publish_metadata(app)
                else:
                    print("Invalid choice. Please enter a number between 1 and 7.")
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await app.close()


if __name__ == "__main__":
    asyncio.run(main())
