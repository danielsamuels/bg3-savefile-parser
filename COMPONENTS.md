# LSMF component census

Every component type in the `LSMF` ECS blob of a mid-campaign save
(`quicksave_maia.lsv`, 355 types), classified by an automated byte-level
pass and cross-referenced against bg3se struct definitions. See
[FORMAT.md §6](FORMAT.md#6-the-lsmf-ecs-blob-newage) for the structures and
conventions (the +48 pointer rule, heap ranges, ownerlists, packed streams).

Columns: name | element size | rows | has ownerlist | payload class |
semantic note. Notes marked `~ X` cite the matching bg3se struct; matches on
generic leaf names (`Component`, `StateComponent`, `MemberComponent`) are
name collisions and unreliable. Tags in the notes:

- `[DECODED]`: read by the parser; documented in FORMAT.md.
- `[PARTIAL-KNOWN]`: structure partly understood; see FORMAT.md.
- `[OTHER-AGENT]`: under active investigation when the census ran.

Patterns that close out whole classes of entries:

- Tag components (element size 1, matching bg3se `DEFINE_TAG_COMPONENT`):
  the byte content is uninitialised junk; presence in the ownerlist is the
  entire payload. `ItemComponent`, `CanMoveComponent`, `SavegameComponent`,
  `IsGlobalComponent` and the other ~25 `u8-varied` singles carry no data.
- Enum-value pools (`E*` / `T*` names, element size 8, no ownerlist, ~85
  types): one u64 per distinct enum value in use, referenced by absolute
  pointer from sibling components (the `ESourceType` mechanism).
- Caches: `TotalSuppliesComponent`, `calendar.v0.StartingDateComponent`, and
  `calendar.v0.DaysPassedComponent` hold stale or dangling values between
  system runs; a singleton that decodes as a heap pointer in one save and a
  value in another is a cache, not a layout mystery.
- The directory is dynamic: a component type appears only when at least one
  entity carries it (tutorial save has 309 types, mid-campaign 355, late
  344; summons/escort/cutscene types come and go with runtime state).
- Monotone growth trackers across a campaign: `RecipeData` (4 → 45 → 47),
  `lock.v0.KeyComponent` (3 → 29 → 33), `background.v0.GoalRecord`
  (absent → 30 → 37), `icons.v1.Icon` (996 → 1707 → 1807).
- Save-embedded images: `icons.v1.Icon` rows for custom-portrait entities
  point at RIFF/WebP image data stored directly in the LSMF heap.

## Census table

```
core.v0.Level | 32 | 1 | N | mixed/opaque | level name + bounds for the loaded level ("WLD_Main_A")
core.v0.EntityId | 16 | 17185 | N | entity-GUIDs | [DECODED] 16-byte entity-instance GUID per entity row — e.g. 00000000-0000-0000-6d75-6e61696f2e64 | 19e1ec72-f642-69f7...
game.action_resources.v1.Component | 16 | 259 | Y | heap-range | [OTHER-AGENT] ~ ls::constellation::Component [HashMap<Guid, InputSocket> Inputs; HashMap<Guid, OutputSocket> Outpu…]
game.ai.combat.v0.ArchetypeComponent | 64 | 1677 | Y | mixed/opaque | ~ esv::ai::combat::ArchetypeComponent [[[bg3::legacy(field_0)]] FixedString ActiveArchetype; [[bg3::legacy(field_4)]] FixedStr...]
game.ai.swarm.v0.MemberComponent | 16 | 18 | Y | heap-ptr +u32-small(6 distinct) | ~ eoc::party::MemberComponent [[[bg3::legacy(UserID)]] int UserId; [[bg3::legacy(field_8)]] Guid UserUuid; EntityH...
game.ai.swarm.v0.Group | 32 | 67 | N | heap-range heap-ptr +mixed | (no ~ match)
game.ai.swarm.v0.GroupsComponent | 16 | 1 | Y | heap-range | (no ~ match)
game.approval.v0.Ratings | 48 | 10 | Y | mixed/opaque | [OTHER-AGENT] ~ eoc::approval::RatingsComponent [HashMap<EntityHandle, int> Ratings; HashSet<Guid> field_70]
game.v0.StateComponent | 8 | 12 | Y | mixed/opaque | ~ eoc::splatter::StateComponent [SplatterState State; glm::vec3 Translate]
game.attitude.v0.AttitudeEntry | 48 | 27 | N | heap-range GUID-like +u32-high-entropy | serialized HashMap<AttitudeIdentifier{character,identity,race,bodytype},int> entry; i32 attitude @+40 (obs. 2...
game.attitude.v0.AttitudesToPlayersComponent | 16 | 258 | Y | opaque(high-entropy) | per-entity head of the AttitudeEntry map (~ HashMap<AttitudeIdentifier,int>)
game.avatar.v0.AvatarComponent | 16 | 1 | Y | opaque(high-entropy) | ~ eoc::tag::AvatarComponent (TAG: presence-only; bytes=junk)
game.background.v0.BackgroundGoals | 32 | 6 | N | GUID-like +mixed | per-character background-goal lists: heap range + background GUID — e.g. ffffffff-ffff-ffff-ffff-ffffffffffff | 00000024-0000-00...
game.background.v0.GoalRecord | 56 | 30 | N | GUID-like +u32-high-entropy | one achieved/known background goal: ids + ptr->"Act1"/"Act2" + goal GUID (inspiration events) — e.g. 00060ba0-0000-0000-0...
game.background.v0.GoalsComponent | 16 | 1 | Y | opaque(high-entropy) | singleton head for background-goal storage
game.body_type.v0.BodyTypeComponent | 16 | 258 | Y | heap-range | ~ eoc::BodyTypeComponent [uint8_t BodyType; uint8_t BodyType2]
game.breadcrumb.v0.BreadcrumbComponent | 32 | 2 | Y | heap-range heap-ptr +mixed | ~ esv::BreadcrumbComponent [std::array<BreadcrumbEvent, 8> field_18; glm::vec3 field_118]
game.calendar.v0.StartingDateComponent | 8 | 1 | Y | opaque(high-entropy) | ~ start date; CACHE: float-pair in maia, stale heap ptr in tutorial/327
game.calendar.v0.DaysPassedComponent | 4 | 1 | Y | u32-enum | ~ int Days; observed values stale/pointer-like in 2 of 3 saves — a cache like TotalSupplies — e.g. values=1126318080
game.camp.v0.TotalSuppliesComponent | 4 | 1 | Y | u32-enum | [DECODED] u32 camp-supply total; CACHE zeroed between camp visits — e.g. values=852
game.camp.v0.QualityComponent | 8 | 1 | Y | mixed/opaque | ~ eoc::camp::QualityComponent [int field_0; int field_4]
game.camp.v0.SupplyComponent | 4 | 29 | Y | u32-varied PACKED? | per-supply-item record; PACKED stream suspect (values misaligned) — e.g. 18 distinct, min=0 max=3263044562
game.camp.v1.EndTheDayStateComponent | 16 | 1 | Y | u32-ish counters | ~ eoc::camp::EndTheDayStateComponent [uint8_t State; EntityHandle field_8]
game.camp.v1.ChestComponent | 48 | 1 | Y | mixed/opaque | camp chest singleton; ~ {STDString, int UserID, FixedString, EntityHandle, int}: on-disk small u32s + u16 pair + ptr
game.camp.v1.PresenceComponent | 1 | 4 | Y | u8-enum | ~ eoc::camp::PresenceComponent (TAG: presence-only; bytes=junk) — e.g. values=0,51,132,230
game.camp.v0.SettingsComponent | 8 | 1 | Y | u32-ish counters PACKED? | ~ eoc::camp::SettingsComponent [uint8_t field_0; uint8_t field_1; int field_4]
game.camp.v0.TriggerComponent | 8 | 4 | Y | mixed/opaque | (no ~ match)
game.capabilities.v0.CanBeLootedComponent | 8 | 258 | Y | mixed/opaque | ~ eoc::CanBeLootedComponent [uint16_t Flags]
game.capabilities.v0.CanDoActionsComponent | 8 | 258 | Y | mixed/opaque | ~ eoc::CanDoActionsComponent [CanDoActionsFlags Flags]
game.capabilities.v0.CanDoRestComponent | 16 | 5 | Y | heap-ptr +mixed | ~ eoc::CanDoRestComponent [RestFlags Flags; [[bg3::legacy(RestErrorFlags1)]] RestErrorFlags LongRestErrorFlags; [[...]
game.capabilities.v2.CanInteractComponent | 16 | 258 | Y | heap-range | ~ eoc::CanInteractComponent [CanInteractFlags Flags; uint16_t Flags2]
game.capabilities.v0.CanModifyHealthComponent | 8 | 258 | Y | mixed/opaque | ~ eoc::CanModifyHealthComponent [uint16_t Flags]
game.capabilities.v1.CanMoveComponent | 24 | 258 | Y | heap-range +mixed | ~ eoc::item_template::CanMoveComponent (TAG: presence-only; bytes=junk)
game.capabilities.v0.CanSenseComponent | 8 | 266 | Y | mixed/opaque | ~ eoc::CanSenseComponent [uint16_t Flags]
game.capabilities.v0.CanSpeakComponent | 8 | 258 | Y | mixed/opaque | ~ eoc::CanSpeakComponent [uint16_t Flags]
game.capabilities.v2.CanTravelComponent | 24 | 258 | Y | heap-range +mixed | ~ eoc::CanTravelComponent [TravelFlags Flags; uint16_t field_2; TravelErrorFlags ErrorFlags]
game.capabilities.v1.CanTriggerRandomCastsComponent | 8 | 258 | Y | mixed/opaque | ~ eoc::CanTriggerRandomCastsComponent (TAG: presence-only; bytes=junk)
game.capabilities.v1.FleeCapabilityComponent | 16 | 258 | Y | mixed/opaque | ~ eoc::FleeCapabilityComponent [FleeErrorFlags Flags; [[bg3::legacy(field_1C)]] float FleeDistance; [[bg3::legacy(field...]
game.character.v0.CharacterComponent | 1 | 258 | Y | u8-varied PACKED? | ~ eoc::character::CharacterComponent (TAG: presence-only; bytes=junk) — e.g. 10 distinct, min=0 max=244
game.character.v0.EquipmentVisualComponent | 8 | 13 | Y | mixed/opaque | ~ eoc::character::EquipmentVisualComponent [uint8_t State]
game.character_creation.v0.BackgroundComponent | 16 | 7 | Y | mixed/opaque | [OTHER-AGENT] ~ eoc::BackgroundComponent [Guid Background]
game.character_creation.v1.AppearanceMaterialSetting | 48 | 72 | N | GUID-like +mixed | [OTHER-AGENT] ~ AppearanceMaterialSetting [Guid Material; Guid Color; float ColorIntensity] — e.g. 5b1e726f-5...
game.character_creation.v3.AppearanceComponent | 112 | 8 | Y | heap-range GUID-like +mixed | [OTHER-AGENT] ~ eoc::character_creation::AppearanceComponent [Array<Guid> Visuals; Array<character_creat...
game.character_creation.v3.LevelUpComponentData | 96 | 88 | N | heap-range template-GUIDs +mixed | [OTHER-AGENT] (no ~ match) — e.g. Rogue | Rogue
game.character_creation.v0.LevelUpComponentAbilities | 16 | 88 | N | heap-range | [OTHER-AGENT] (no ~ match)
game.character_creation.v2.LevelUpComponentSelectors | 112 | 88 | N | opaque(high-entropy) | [OTHER-AGENT] (no ~ match)
game.character_creation.v1.SelectorMeta | 48 | 118 | N | template-GUIDs +mixed | [OTHER-AGENT] (no ~ match) — e.g. Rogue | Rogue
game.character_creation.v2.BaseSelector | 32 | 118 | N | heap-ptr +u32-small(42 distinct) | [OTHER-AGENT] (no ~ match)
game.character_creation.v1.AbilityAddSlot | 8 | 46 | N | mixed/opaque | [OTHER-AGENT] (no ~ match)
game.character_creation.v2.AbilityBonusSelector | 56 | 14 | N | heap-range heap-ptr +u32-high-entropy | [OTHER-AGENT] ~ AbilityBonusSelector [Guid AbilityBonus; [[bg3::legacy(Array_b8)]] Array<Abil...
game.character_creation.v1.SkillAddSlot | 8 | 44 | N | heap-ptr | [OTHER-AGENT] (no ~ match)
game.character_creation.v2.SkillSelector | 40 | 18 | N | GUID-like heap-ptr | [OTHER-AGENT] ~ SkillSelector [Guid Skill; [[bg3::legacy(Array_b8)]] Array<SkillId> Proficiencies; STDString field_60] ...
game.character_creation.v2.SkillExpertiseSelector | 48 | 4 | N | GUID-like heap-ptr +mixed | [OTHER-AGENT] ~ SkillExpertiseSelector [[[bg3::legacy(field_38)]] Guid Skill; uint8_t field_48; [[bg3::l...
game.character_creation.v1.StringViewAddSlot | 16 | 104 | N | heap-ptr +mixed | [OTHER-AGENT] (no ~ match)
game.character_creation.v2.SpellSelector | 56 | 44 | N | heap-range heap-ptr +u32-high-entropy | [OTHER-AGENT] ~ SpellSelector [}; Guid SpellList; Array<FixedString> Spells]
game.character_creation.v2.AbilitySelector | 40 | 10 | N | GUID-like +mixed | [OTHER-AGENT] (no ~ match) — e.g. 663db14f-ecc0-c525-3598-000700000000 | 00071788-0000-0000...
game.character_creation.v1.StringViewReplaceSlot | 32 | 32 | N | heap-ptr +mixed | [OTHER-AGENT] (no ~ match)
game.character_creation.v2.PassiveSelector | 56 | 28 | N | GUID-like heap-ptr +mixed | [OTHER-AGENT] ~ PassiveSelector [}; [[bg3::legacy(SpellList)]] Guid PassiveList; [[bg3::legacy(Spells)]] Array...
game.character_creation.v3.LevelUpComponent | 16 | 7 | Y | mixed/opaque | [OTHER-AGENT] ~ eoc::character_creation::LevelUpComponent [Array<LevelUpData> LevelUps]
game.character_creation.v0.StateComponent | 1 | 7 | Y | u8-enum PACKED? | [OTHER-AGENT] ~ eoc::character_creation::StateComponent [bool HasDummy; bool Canceled; uint8_t field_2] — e.g. values=0,32,...
game.character_creation.v1.CharacterCreationStatsComponent | 88 | 7 | Y | heap-range GUID-like heap-ptr +u32-small(9 distinct) | [OTHER-AGENT] ~ eoc::CharacterCreationStatsComponent [Guid Race; Gui...
game.character_creation.v0.OriginComponent | 16 | 7 | Y | mixed/opaque | [OTHER-AGENT] ~ eoc::OriginComponent [Guid field_18; FixedString Origin]
game.character_creation.v0.VoiceComponent | 16 | 7 | Y | GUID-like | [OTHER-AGENT] ~ eoc::VoiceComponent [Guid Voice] — e.g. b8b4a974-b045-45f6-9516-b457b8773abd | 2bb39cf2-4649-4238...
game.character_creation.v0.AppearanceVisualTagComponent | 16 | 3 | Y | GUID-like | [OTHER-AGENT] ~ esv::character_creation::AppearanceVisualTagComponent [Array<Guid> Tags] — e.g. e79ada7e-e9be-4582...
game.character_creation.v0.GodComponent | 16 | 7 | Y | mixed/opaque | [OTHER-AGENT] ~ esv::character_creation::GodComponent [Guid God]
game.character_creation.v0.IsCustomComponent | 1 | 2 | Y | all-zero | [OTHER-AGENT] ~ esv::character_creation::IsCustomComponent (TAG: presence-only; bytes=junk)
game.combat.v0.ParticipantComponent | 48 | 1675 | Y | GUID-like +mixed | ~ eoc::combat::ParticipantComponent [EntityHandle CombatHandle; FixedString CombatGroupId; [[bg3::legacy(field_C)]] int Init...
game.combat.v0.CanStartCombatComponent | 1 | 225 | Y | u8-varied PACKED? | ~ esv::combat::CanStartCombatComponent (TAG: presence-only; bytes=junk) — e.g. 33 distinct, min=0 max=255
game.spell.v0.SpellSource | 24 | 5939 | N | template-GUIDs +mixed | (no ~ match) — e.g. Rogue | Fiend
game.spell.v0.MetaId | 24 | 5939 | N | heap-ptr +mixed | (no ~ match)
game.spell.v0.SpellId | 24 | 3631 | N | heap-range +u32-small(72 distinct) | [DECODED] ~ SpellId [FixedString Prototype]
game.concentration.v0.ConcentrationComponent | 24 | 258 | Y | heap-ptr +u32-high-entropy | [OTHER-AGENT] ~ eoc::concentration::ConcentrationComponent [[[bg3::legacy(field_0)]] EntityHandle Caster; ...
game.cooldown.v0.PerItemSpellCooldownComponent | 16 | 1 | Y | mixed/opaque | (no ~ match)
game.darkness.v1.DarknessComponent | 32 | 258 | Y | heap-range heap-ptr +u32-small(3 distinct) | ~ eoc::DarknessComponent [uint8_t Sneaking; uint8_t Obscurity; [[bg3::legacy(field_2)]] bool Sneakin...
game.darkness.v0.DarknessActiveComponent | 1 | 10 | Y | all-zero | ~ esv::darkness::DarknessActiveComponent (TAG: presence-only; bytes=junk)
game.death.v0.DeadByDefaultComponent | 1 | 2 | Y | all-zero | [OTHER-AGENT] ~ eoc::death::DeadByDefaultComponent [uint8_t DeadByDefault]
game.death.v4.DeathData | 144 | 36 | N | GUID-like +mixed | [OTHER-AGENT] ~ DeathData [EntityHandle Cause; EntityHandle CauseOwner; Guid CauseUuid] — e.g. 002d5b48-0000-0000-0000-000000000000 | 850...
game.death.v4.DeathComponent | 8 | 36 | Y | heap-ptr | [OTHER-AGENT] ~ eoc::death::DeathComponent [FixedString Animation; float HealthPercentage}; bool IsResurrected}]
game.death.v1.DeathTypeComponent | 8 | 36 | Y | heap-ptr | [OTHER-AGENT] ~ eoc::death::DeathTypeComponent [uint8_t DeathType]
game.death.v1.StateComponent | 4 | 36 | Y | u32-enum | [OTHER-AGENT] ~ eoc::death::StateComponent [uint32_t State] — e.g. values=0,7,2972512,2972520
game.death.v1.DelayDeathReasons | 4 | 258 | N | u32-enum | [OTHER-AGENT] (no ~ match) — e.g. values=0,2,7
game.death.v2.DelayDeathCauseComponent | 32 | 258 | Y | heap-ptr +u32-small(123 distinct) | [OTHER-AGENT] ~ esv::death::DelayDeathCauseComponent [int DelayCount; int Reason; Guid field_8]
game.v1.DetachedComponent | 8 | 1 | Y | opaque(high-entropy) | ~ eoc::DetachedComponent [uint32_t Flags]
game.dialog.v1.ADRateLimitingDataComponent | 32 | 2 | Y | GUID-like +mixed | (no ~ match) — e.g. 000e8c04-0000-0000-ab61-f0d8aba8d988 | 8213542b-c23f-1dd6...
game.dialog.v0.ADRateLimitingHistoryComponent | 16 | 1 | Y | mixed/opaque | (no ~ match)
game.dialog.v0.StateComponent | 1 | 258 | Y | u8-varied PACKED? | ~ eoc::dialog::StateComponent [uint8_t field_0; uint8_t field_1; uint8_t field_2] — e.g. 27 distinct, min=0 max=249
game.display_names.v0.DisplayNameTS | 32 | 3113 | N | heap-ptr +mixed | (no ~ match)
core.v0.TranslatedString | 32 | 4846 | N | heap-ptr +mixed | TranslatedString handles (ptr+len into handle pool) for entity display text
game.display_names.v1.DisplayTitleTS | 16 | 48 | N | heap-ptr +u32-small(5 distinct) | (no ~ match)
game.display_names.v2.Component | 40 | 1677 | Y | heap-range +u32-high-entropy | ~ ls::constellation::Component [HashMap<Guid, InputSocket> Inputs; HashMap<Guid, OutputSocket> Outpu…]
game.dual_wielding.v0.DualWieldingComponent | 7 | 258 | Y | u32-ish counters PACKED? | dual-wield toggle flags; elem=7 (odd) and PACKED — rows straddle the grid
game.escort.v0.MemberComponent | 16 | 1 | Y | all-zero | ~ esv::escort::MemberComponent [FixedString Group]
game.escort.v0.Group | 32 | 1 | N | all-zero | (no ~ match)
game.escort.v0.GroupsSingletonComponent | 16 | 1 | Y | mixed/opaque | (no ~ match)
game.experience.v0.AvailableLevelComponent | 4 | 258 | Y | u32-varied | [OTHER-AGENT] ~ eoc::exp::AvailableLevelComponent [int Level] — e.g. 20 distinct, min=0 max=3482336
game.experience.v0.ExperienceComponent | 12 | 4 | Y | u32-ish counters | [OTHER-AGENT] ~ eoc::exp::ExperienceComponent [int CurrentLevelExperience; int NextLevelExperience; int TotalExperi…]
game.experience.v0.ExperienceGaveOutComponent | 4 | 233 | Y | u32-varied PACKED? | [OTHER-AGENT] ~ esv::exp::ExperienceGaveOutComponent [int Experience] — e.g. 27 distinct, min=0 max=608358912
game.fog_volume_requests.v0.Component | 16 | 1 | Y | u32-ish counters | ~ ls::constellation::Component [HashMap<Guid, InputSocket> Inputs; HashMap<Guid, OutputSocket> Outpu…]
game.game_timer.v1.GameTimerComponent | 48 | 12 | Y | string-pool refs +mixed | named script timers: {ptr->name,u32 len} + f32 elapsed/duration pairs — e.g. GLO_Spells_DominatedPADWindow | WorldGos...
game.god.v0.GodComponent | 40 | 7 | Y | mixed/opaque | [OTHER-AGENT] ~ eoc::god::GodComponent [Guid God; std::optional<Guid> GodOverride]
game.god.v0.TagComponent | 16 | 7 | Y | opaque(high-entropy) | [OTHER-AGENT] ~ eoc::god::TagComponent [Array<Guid> Tags]
game.gravity.v0.GravityDisabledComponent | 1 | 79 | Y | u8-varied PACKED? | [PARTIAL-KNOWN] PARTIAL-KNOWN: physics off because attached to character (tag) — e.g. 13 distinct, min=0 max=255
game.gravity.v0.GravityDisabledUntilMovedComponent | 40 | 13 | Y | GUID-like +u32-high-entropy | ~ eoc::GravityDisabledUntilMovedComponent [Transform Transform] — e.g. ffffffff-ffff-ffff-0000-00000...
game.hotbar.v5.Container | 16 | 14 | N | mixed/opaque | [OTHER-AGENT] ~ eoc::hotbar::ContainerComponent [HashMap<FixedString, Array<Bar>> Containers; FixedString ActiveConta…]
game.hotbar.v5.Bar | 56 | 196 | N | heap-range +mixed | [OTHER-AGENT] ~ Bar [uint8_t Index}; uint8_t field_1}; Array<Slot> Elements]
game.hotbar.v2.Slot | 48 | 631 | N | heap-ptr +mixed | [OTHER-AGENT] ~ Slot [FixedString Slot; FixedString VisualResource; FixedString Bone]
game.hotbar.v5.Component | 56 | 13 | Y | heap-range GUID-like heap-ptr +u32-small(4 distinct) | [OTHER-AGENT] ~ ls::constellation::Component [HashMap<Guid, InputSocket> Inputs; HashMap<Guid, Output...
game.hotbar.v0.OrderComponent | 1 | 13 | Y | u8-enum PACKED? | [OTHER-AGENT] ~ esv::hotbar::OrderComponent (TAG: presence-only; bytes=junk) — e.g. values=0,19,38,53,128,175,192
game.icon.v0.CustomIconData | 32 | 1 | N | heap-range +mixed | custom icon payload descriptor: heap range + {ptr,len} into WebP data
game.icon.v0.CustomIconsStorageComponent | 16 | 1 | Y | mixed/opaque | singleton head for custom icon storage
game.icon.v0.CharacterCreationCustomIconComponent | 16 | 7 | Y | heap-range | CC custom icon GUID per created character
game.icons.v1.Icon | 24 | 1707 | N | GUID-like heap-ptr | icon records: ptrs to RIFF/WebP blobs (custom icons embedded in heap!) + icon-name pool refs — e.g. 00361bee-0000-0000-1bee-003600000000 | ...
game.icons.v2.Component | 16 | 1677 | Y | heap-range | ~ ls::constellation::Component [HashMap<Guid, InputSocket> Inputs; HashMap<Guid, OutputSocket> Outpu…]
game.identity.v0.IdentityComponent | 8 | 11 | Y | heap-ptr | [OTHER-AGENT] ~ eoc::identity::IdentityComponent [uint8_t field_0]
game.identity.v0.OriginalIdentityComponent | 8 | 7 | Y | heap-ptr | [OTHER-AGENT] ~ eoc::identity::OriginalIdentityComponent [uint8_t field_0]
game.identity.v0.StateComponent | 8 | 13 | Y | heap-ptr | [OTHER-AGENT] ~ eoc::identity::StateComponent [[[bg3::legacy(field_0)]] bool Disguised]
game.improvisedweapon.v0.CanBeWieldedComponent | 1 | 379 | Y | u8-varied PACKED? | ~ eoc::improvised_weapon::CanBeWieldedComponent (TAG: presence-only; bytes=junk) — e.g. 15 distinct, min=0 max=208
game.interrupt.v0.PreferencesComponent | 32 | 238 | Y | heap-range | per-entity interrupt ask/auto preferences: heap ranges -> Interrupt_* name list
game.inventory.v0.CanBeInComponent | 1 | 1396 | Y | u8-varied | ~ eoc::inventory::CanBeInComponent (TAG: presence-only; bytes=junk) — e.g. 58 distinct, min=0 max=216
game.inventory.v0.CannotBeTakenOutComponent | 1 | 1 | Y | all-zero | ~ eoc::inventory::CannotBeTakenOutComponent (TAG: presence-only; bytes=junk)
game.inventory.v0.ContainerSlotData | 16 | 1280 | N | heap-ptr +u32-small(197 distinct) | [DECODED] ~ ContainerSlotData [EntityHandle Item; uint32_t field_8}]
game.inventory.v1.ContainerComponent | 32 | 564 | Y | mixed/opaque | [DECODED] ~ eoc::inventory::ContainerComponent [HashMap<uint16_t, ContainerSlotData> Items]
game.inventory.v3.Type | 8 | 564 | N | u32-ish counters | ~ eoc::trigger::TypeComponent [uint8_t Type]
game.inventory.v4.DataComponent | 16 | 564 | Y | GUID-like | ~ eoc::inventory::DataComponent [[[bg3::legacy(field_0)]] InventoryType Type; [[bg3::legacy(Flags)]] uint16_t SlotLimit] — e.g. 00000001...
game.inventory.v1.IsOwnedComponent | 8 | 564 | Y | heap-ptr | [DECODED] ~ eoc::inventory::IsOwnedComponent [EntityHandle Owner]
game.inventory.v0.MemberData | 16 | 1314 | N | heap-ptr +mixed | [PARTIAL-KNOWN] PARTIAL-KNOWN: per inventory-member {ptr_a -> shadow container, ptr_b}
game.inventory.v0.MemberComponent | 8 | 1314 | Y | heap-ptr | [PARTIAL-KNOWN] PARTIAL-KNOWN: item is an inventory member; ptr to MemberData
game.inventory.v0.OwnerComponent | 24 | 306 | Y | heap-range heap-ptr | [DECODED] ~ eoc::inventory::OwnerComponent [Array<EntityHandle> Inventories; EntityHandle PrimaryInventory]
game.inventory.v0.StackEntry | 8 | 199 | N | mixed/opaque | [DECODED] ~ StackEntry [uint16_t EntityIndex}; uint32_t Quantity}]
game.inventory.v0.Stack | 32 | 157 | N | heap-range | ~ eoc::inventory::StackComponent [[[bg3::legacy(Arr_u64)]] Array<EntityHandle> Elements; [[bg3::legacy(Arr_u8)]] Array<St...]
game.inventory.v0.NewStackComponent | 8 | 157 | Y | heap-ptr | [DECODED] (no ~ match)
game.inventory.v0.StackMemberComponent | 8 | 191 | Y | heap-ptr | ~ eoc::inventory::StackMemberComponent [EntityHandle Stack]
game.inventory.v0.WieldedComponent | 16 | 116 | Y | GUID-like | [PARTIAL-KNOWN] PARTIAL-KNOWN: item is/was in a weapon slot (16B id pairs) — e.g. 0001d1b8-0000-0000-d1c8-000100000000 | 0001d1d8-000...
game.inventory.v0.WieldingHistoryComponent | 16 | 6 | Y | GUID-like | ~ eoc::inventory::WieldingHistoryComponent [Guid field_0] — e.g. 0a5a9d2b-ec21-ed3e-49c1-a63963c733e0 | 25721313-0c15-4935...
game.inventory.v0.WieldingComponent | 8 | 392 | Y | heap-ptr | ~ eoc::improvised_weapon::WieldingComponent [EntityHandle Weapon]
game.inventory.v0.CharacterHasGeneratedTradeTreasureComponent | 1 | 10 | Y | u8-enum PACKED? | ~ esv::inventory::CharacterHasGeneratedTradeTreasureComponent (TAG: presence-only; bytes=junk) — e.g. ...
game.inventory.v1.ContainerDataComponent | 8 | 564 | Y | u32-ish counters | ~ esv::inventory::ContainerDataComponent [uint16_t Flags; int field_4]
game.inventory.v1.EntityHasGeneratedTreasureComponent | 1 | 79 | Y | u8-varied PACKED? | ~ esv::inventory::EntityHasGeneratedTreasureComponent (TAG: presence-only; bytes=junk) — e.g. 10 distinct, m...
game.inventory.v0.LootableReactionQueueSingletonComponent | 32 | 1 | Y | mixed/opaque | (no ~ match)
game.inventory.v0.ShapeshiftEquipmentHistoryComponent | 16 | 11 | Y | mixed/opaque | ~ esv::inventory::ShapeshiftEquipmentHistoryComponent [Array<Guid> History]
game.inventory.v0.InventoryPropertyIsDroppedOnDeathComponent | 24 | 232 | Y | GUID-like +u32-high-entropy | ~ esv::InventoryPropertyIsDroppedOnDeathComponent [GenericPropertyTag Tag] — e.g. 00375c1...
game.inventory.v0.InventoryPropertyIsTradableComponent | 24 | 232 | Y | GUID-like +u32-high-entropy | ~ esv::InventoryPropertyIsTradableComponent [GenericPropertyTag Tag] — e.g. cdd7e401-54f4-0003-...
game.invisibility.v6.InvisibilityComponent | 24 | 62 | Y | GUID-like +mixed | invisibility state: ptr + f32 xyz (last seen position) — e.g. 002d5c20-0000-0000-12ba-9440c0f0410a | 002d5c20-0000-0000...
game.item.v0.HasMovedComponent | 1 | 75 | Y | u8-varied | ~ eoc::item::HasMovedComponent (TAG: presence-only; bytes=junk) — e.g. 34 distinct, min=0 max=255
game.item.v0.HasOpenedComponent | 1 | 42 | Y | u8-varied | ~ eoc::item::HasOpenedComponent (TAG: presence-only; bytes=junk) — e.g. 14 distinct, min=0 max=255
game.item.v0.ItemComponent | 1 | 1419 | Y | u8-varied | ~ eoc::item::ItemComponent (TAG: presence-only; bytes=junk) — e.g. 254 distinct, min=0 max=255
game.item.v0.CanMoveComponent | 1 | 1362 | Y | u8-varied | ~ eoc::item_template::CanMoveComponent (TAG: presence-only; bytes=junk) — e.g. 252 distinct, min=0 max=255
game.item.v0.InteractionDisabledComponent | 1 | 34 | Y | u8-varied | ~ eoc::item_template::InteractionDisabledComponent (TAG: presence-only; bytes=junk) — e.g. 33 distinct, min=6 max=240
game.item.v0.IsStoryItemComponent | 1 | 66 | Y | u8-varied PACKED? | ~ eoc::item_template::IsStoryItemComponent (TAG: presence-only; bytes=junk) — e.g. 39 distinct, min=0 max=255
game.item.animation.v0.RequestComponent | 16 | 47 | Y | mixed/opaque | (no ~ match)
game.item.animation.v0.PendingRequestComponent | 8 | 3 | Y | constant | (no ~ match) — e.g. row=405c2d0000000000
game.item.animation.v0.StateComponent | 24 | 47 | Y | heap-range +mixed | ~ eoc::splatter::StateComponent [SplatterState State; glm::vec3 Translate]
game.jumpfollow.v0.JumpFollowComponent | 56 | 4 | Y | opaque(high-entropy) | ~ esv::JumpFollowComponent [glm::vec3 field_0; glm::vec3 field_C; int field_18]
game.v0.InventoryItemDataPopulatedComponent | 1 | 1560 | Y | u8-varied | ~ esv::level::InventoryItemDataPopulatedComponent (TAG: presence-only; bytes=junk) — e.g. 248 distinct, min=0 max=255
game.lock.v0.KeyComponent | 16 | 29 | Y | mixed/opaque | ~ FixedString Key: {ptr->key name,u32 len(verified),tag} e.g. TUT_SharChest, CHA_Crypt_Key; first 3 rows hold u32-handle form instead
game.lock.v0.V1LockComponent | 32 | 2 | Y | heap-ptr +mixed | locks: {ptr->key name, len, tag} x2 (lock + matching key)
game.lootvalidation.v4.LootComponent | 2 | 258 | Y | u16-varied | ~ eoc::LootComponent [uint8_t Flags; uint8_t InventoryType] — e.g. 25 distinct, min=0 max=62209
game.v0.LevelIsOwnerComponent | 1 | 2061 | Y | u8-varied | ~ ls::LevelIsOwnerComponent (TAG: presence-only; bytes=junk) — e.g. 200 distinct, min=0 max=255
game.v0.SavegameComponent | 1 | 2082 | Y | u8-varied PACKED? | ~ ls::SavegameComponent (TAG: presence-only; bytes=junk) — e.g. 203 distinct, min=0 max=255
game.v0.SaveWithComponent | 8 | 573 | Y | heap-ptr | (no ~ match)
game.v0.IsGlobalComponent | 1 | 2646 | Y | u8-varied PACKED? | ~ ls::IsGlobalComponent (TAG: presence-only; bytes=junk) — e.g. 20 distinct, min=0 max=253
game.materialparameteroverride.v0.MaterialParameterOverride | 32 | 1 | Y | all-zero | ~ eoc::MaterialParameterOverrideComponent [Array<Guid> field_0; Array<MaterialParameterOverride> field_10]
game.multiplayer.v2.NewPlayerJoinBlockedSingletonComponent | 8 | 1 | Y | all-zero | (no ~ match)
game.v0.OffStageComponent | 1 | 61 | Y | u8-varied | ~ eoc::OffStageComponent (TAG: presence-only; bytes=junk) — e.g. 12 distinct, min=0 max=255
game.v0.OwnedAsLootComponent | 1 | 943 | Y | u8-varied PACKED? | [PARTIAL-KNOWN] PARTIAL-KNOWN: item owned as loot by a character (tag; weak worn/carried tiebreaker) — e.g. 117 distinct, min=0 max=255
game.v0.OwneeCurrentComponent | 8 | 1419 | Y | mixed/opaque | ~ eoc::ownership::OwneeCurrentComponent [EntityHandle Ownee]
game.v2.OwneeHistoryComponent | 24 | 1419 | Y | heap-ptr +mixed | ~ esv::ownership::OwneeHistoryComponent [EntityHandle OriginalOwner; EntityHandle LatestOwner; EntityHandle P…]
game.v0.IsCurrentOwnerComponent | 16 | 166 | Y | heap-range | ~ esv::ownership::IsCurrentOwnerComponent [HashSet<EntityHandle> Owner]
game.v0.IsLatestOwnerComponent | 16 | 166 | Y | heap-range | ~ esv::ownership::IsLatestOwnerComponent [HashSet<EntityHandle> Owner]
game.v1.IsPreviousOwnerComponent | 16 | 10 | Y | heap-range | ~ esv::ownership::IsPreviousOwnerComponent [HashSet<EntityHandle> Owner]
game.v0.IsOriginalOwnerComponent | 16 | 168 | Y | heap-range | ~ esv::ownership::IsOriginalOwnerComponent [HashSet<EntityHandle> Owner]
game.v0.OwneeRequestComponent | 32 | 1419 | Y | opaque(high-entropy) | ~ esv::ownership::OwneeRequestComponent [std::optional<EntityHandle> NewCurrentOwnee; std::optional<EntityHan…]
game.onetimereward.v0.RewardListComponent | 16 | 1 | Y | mixed/opaque | (no ~ match)
game.party.v0.CompositionComponent | 32 | 1 | Y | opaque(high-entropy) | ~ eoc::party::CompositionComponent [EntityHandle Party; [[bg3::legacy(field_8)]] Guid PartyUuid; Array<Member> Members]
game.party.v0.MemberComponent | 48 | 5 | Y | GUID-like +mixed | ~ eoc::party::MemberComponent [[[bg3::legacy(UserID)]] int UserId; [[bg3::legacy(field_8)]] Guid UserUuid; EntityHandl...] — e.g. 003...
game.party.v0.PortalsComponent | 16 | 1 | Y | opaque(high-entropy) | ~ eoc::party::PortalsComponent [HashSet<EntityHandle> Portals]
game.party.v0.RecipeData | 24 | 45 | N | string-pool refs heap-ptr | ~ Recipe{FixedString,u8}: {ptr->recipe stat name, u64 len(verified exact), u8 flag+tag} — e.g. ALCH_Potion_Healing_RoguesMorsel ...
game.party.v1.RecipesComponent | 16 | 1 | Y | string-pool refs | party singleton, ~ Array<Recipe>: {ptr,count} head over the 45 RecipeData rows — e.g. ALCH_Extract_SpiderGland
game.party.v0.ViewComponent | 1 | 1 | Y | bool-flags PACKED? | ~ eoc::party::ViewComponent [[[bg3::legacy(field_0)]] Guid PartyUuid; Array<View> Views; Array<EntityHandle> Characters] — e.g. values=1
game.party.v0.WaypointsComponent | 16 | 1 | Y | string-pool refs | party singleton, ~ HashSet<Waypoint{FixedString name,Guid,FixedString level}>: {ptr,count}; unlocked WAYP_* names sit in the adjac...
game.party.v0.UserGroupSnapshot | 16 | 1 | N | heap-range | (no ~ match)
game.party.v0.UserSnapshotComponent | 32 | 1 | Y | heap-range +mixed | ~ esv::party::UserSnapshotComponent [[[bg3::legacy(Snapshot)]] HashMap<Guid, Array<Array<EntityHandle>>> PerUserCharacters]
game.passives.v0.PersistentDataComponent | 8 | 1677 | Y | u32-ish counters | [OTHER-AGENT] ~ esv::passive::PersistentDataComponent [float field_0; float field_4]
game.passives.v0.ToggledPassivesComponent | 32 | 42 | Y | heap-range | [OTHER-AGENT] ~ esv::passive::ToggledPassivesComponent [HashMap<FixedString, bool> Passives]
game.passives.v1.UsageCountComponent | 32 | 7 | Y | heap-range | [OTHER-AGENT] ~ eoc::passive::UsageCountComponent [HashMap<FixedString, PassiveUsageCount> Passives]
game.passives.v0.ScriptPassivesComponent | 16 | 2 | Y | heap-range | [OTHER-AGENT] ~ esv::passive::ScriptPassivesComponent [HashSet<FixedString> Passives]
game.patrol.v1.CaretComponent | 72 | 7 | Y | GUID-like +mixed | (no ~ match) — e.g. 0037f5d0-0000-0000-f5e0-003700000000 | c2b08000-0e00-419c...
game.pickpocket.v0.PickpocketComponent | 16 | 258 | Y | opaque(high-entropy) | ~ esv::pickpocket::PickpocketComponent [[[bg3::legacy(field_18)]] Array<PickpocketAttempt> Items]
game.pickpocket.v0.InventoryPropertyCanBePickpocketedComponent | 24 | 232 | Y | GUID-like +u32-high-entropy | ~ esv::InventoryPropertyCanBePickpocketedComponent [GenericPropertyTag Tag] — e.g. ffff...
game.v0.PlayerComponent | 1 | 5 | Y | u8-enum | tag: player-controlled entity (5 rows = 4 party + 1) — e.g. values=1,205,215,228,244
game.v0.ClientControlComponent | 1 | 1 | Y | u8-enum PACKED? | ~ eoc::ClientControlComponent (TAG: presence-only; bytes=junk) — e.g. values=84
game.progression.v3.LevelUpComponent | 16 | 258 | Y | opaque(high-entropy) | ~ eoc::progression::LevelUpComponent [[[bg3::legacy(field_18)]] Array<LevelUpData> LevelUps]
game.quest.v0.ModifiedJournalEntrySingletonComponent | 32 | 1 | Y | opaque(high-entropy) | (no ~ match)
game.race.v0.RaceComponent | 16 | 258 | Y | opaque(high-entropy) | ~ eoc::RaceComponent [Guid Race]
game.recruit.v0.RecruiterComponent | 16 | 1 | Y | opaque(high-entropy) | ~ eoc::recruit::RecruiterComponent [HashSet<EntityHandle> Recruiters]
game.recruit.v0.RecruitedByComponent | 8 | 5 | Y | mixed/opaque | origin chars -> 8-byte user/recruiter hash (2 distinct values across 5 rows)
game.relation.v1.FactionRelation | 24 | 1583 | N | heap-range +mixed | [OTHER-AGENT] (no ~ match)
game.relation.v0.RelationFactions | 32 | 1591 | N | GUID-like | [OTHER-AGENT] (no ~ match) — e.g. 00000000-0000-0000-28f0-001b00000000 | 4be9261a-e481-8d9d...
game.relation.v2.RelationComponent | 128 | 1 | Y | heap-range +u32-high-entropy | [OTHER-AGENT] ~ eoc::relation::RelationComponent [HashMap<uint32_t, uint8_t> field_0; HashMap<uint32_t, uint8_t> fi...
game.relation.v0.FactionComponent | 40 | 1677 | Y | opaque(high-entropy) | [OTHER-AGENT] ~ eoc::relation::FactionComponent [EntityHandle field_0; Guid field_8; Guid field_18]
game.repose.v2.StateComponent | 48 | 5 | Y | GUID-like +mixed | rest/repose state: u64 + GUID + f32 xyz position (camp bedroll spot) — e.g. 376e33c4-dd15-4c46-a586-87d8b421a0c7 | eba2bcd1-7565-d3d1...
game.repose.v0.UsedEntitiesToCleanSingletonComponent | 16 | 1 | Y | mixed/opaque | (no ~ match)
game.roll.stream.v1.StreamsComponent | 32 | 1 | Y | mixed/opaque | ~ esv::roll::stream::StreamsComponent [Array<Stream> Streams; uint64_t LastFrame; uint64_t BaseSeed]
game.safe_position.v0.SafePositionComponent | 16 | 258 | Y | GUID-like | ~ esv::SafePositionComponent [glm::vec3 Position; bool field_24] — e.g. ffffffff-ffff-ffff-ffff-ffffffffffff | 0037f7f0-0000...
game.shapeshift.v0.ChangeInt | 16 | 13 | N | mixed/opaque | [OTHER-AGENT] (no ~ match)
game.shapeshift.v1.SharedShapeshiftComponent | 72 | 1677 | Y | heap-range heap-ptr +mixed | [OTHER-AGENT] (no ~ match)
game.shapeshift.v0.HealthReservationComponent | 32 | 1677 | Y | opaque(high-entropy) | [OTHER-AGENT] ~ esv::shapeshift::HealthReservationComponent [HashMap<Guid, int32_t> Reservations]
game.shapeshift.v6.State | 688 | 11 | N | string-pool refs heap-range GUID-like heap-ptr +mixed | [OTHER-AGENT] ~ eoc::shapeshift::StateComponent [std::optional<uint8_t> BloodSurfaceType; std::opti...
game.shapeshift.v6.ServerShapeshiftComponent | 16 | 1677 | Y | opaque(high-entropy) | [OTHER-AGENT] (no ~ match)
game.sight.v0.DataComponent | 16 | 1677 | Y | GUID-like | ~ eoc::sight::DataComponent [[[bg3::legacy(field_0)]] Guid SightUuid; [[bg3::legacy(field_10)]] float DarkvisionRang...] — e.g. ffffffff-ff...
game.sight.v0.EntityViewshedComponent | 16 | 310 | Y | opaque(high-entropy) | ~ eoc::sight::EntityViewshedComponent [[[bg3::legacy(field_0)]] HashSet<Guid> Viewshed]
game.sight.v0.ViewshedParticipantComponent | 32 | 308 | Y | GUID-like +u32-high-entropy | ~ esv::sight::ViewshedParticipantComponent [glm::vec3 Position; HashSet<EntityHandle> CanSee] — e.g. ffffff...
game.spell.v1.SpellMeta | 64 | 11 | N | heap-range heap-ptr +mixed | ~ SpellMeta [SpellMetaId SpellId; EntityHandle BoostHandle; [[bg3::legacy(SelectionType)]] SpellLear...]
game.spell.v1.AddedSpellsComponent | 16 | 258 | Y | opaque(high-entropy) | ~ eoc::spell::AddedSpellsComponent [Array<SpellMeta> Spells]
game.spell.v3.SpellData | 72 | 2728 | N | heap-range heap-ptr +mixed | [DECODED] ~ SpellData [SpellId Id; [[bg3::legacy(SpellUUID)]] Guid PreferredCastingResource; int32_t UsedCharges}]
game.spell.v2.CastRequirements | 16 | 8184 | N | mixed/opaque | ~ CastRequirements [[[bg3::legacy(field_0)]] uint8_t CastContext}; [[bg3::legacy(field_4)]] CastRequirement...]
game.spell.v3.SpellBookComponent | 16 | 347 | Y | heap-range | [DECODED] (no ~ match)
game.spell.v1.CooldownData | 48 | 3 | N | heap-range heap-ptr +mixed | ~ CooldownData [SpellId SpellId; SpellCooldownType CooldownType}; [[bg3::legacy(field_29)]] SpellCooldo...]
game.spell.v1.SpellBookCooldowns | 16 | 258 | Y | opaque(high-entropy) | ~ SpellBookCooldownsComponent [Array<CooldownData> Cooldowns]
game.spell.v0.SpellBookPrepares | 80 | 258 | Y | heap-range | [DECODED] (no ~ match)
game.spell.v0.CCPrepareSpellComponent | 16 | 7 | Y | mixed/opaque | ~ eoc::spell::CCPrepareSpellComponent [Array<SpellMetaId> Spells]
game.spell.v0.SpellsLearnedByClass | 32 | 1 | N | heap-range +u32-high-entropy | singleton: heap ranges of spells learned per class
game.spell.v0.LearnedSpells | 32 | 258 | Y | opaque(high-entropy) | ~ eoc::spell::LearnedSpellsComponent [[[bg3::legacy(field_18)]] HashMap<Guid, HashSet<FixedString>> ClassSpells; HashSet<Spel...]
game.spell.v0.PlayerPrepareSpellComponent | 24 | 7 | Y | opaque(high-entropy) | ~ eoc::spell::PlayerPrepareSpellComponent [Array<SpellMetaId> Spells; [[bg3::legacy(field_30)]] bool CharacterCreatio...
game.spell.v0.ScriptedExplosionComponent | 16 | 8 | Y | mixed/opaque | ~ eoc::spell::ScriptedExplosionComponent [FixedString Projectile]
game.spell.v0.OnDamageSpell | 32 | 8 | N | heap-ptr +mixed | ~ OnDamageSpell [FixedString Spell; int field_4}; uint8_t field_8}]
game.spell.v0.OnDamageSpellsComponent | 16 | 8 | Y | mixed/opaque | ~ esv::spell::OnDamageSpellsComponent [Array<OnDamageSpell> Spells]
game.spell_cast.v0.SpellData | 56 | 11 | N | heap-range GUID-like heap-ptr +mixed | ~ SpellData [SpellId Id; [[bg3::legacy(SpellUUID)]] Guid PreferredCastingResource; int32_t UsedCharges}] — e.g. 0...
game.spell_cast.v0.DataCacheSingletonComponent | 16 | 1 | Y | mixed/opaque | ~ eoc::spell_cast::DataCacheSingletonComponent [HashMap<Guid, DataCache> Spells]
game.splatter.v0.StateComponent | 28 | 258 | Y | GUID-like +mixed | ~ eoc::splatter::StateComponent [SplatterState State; glm::vec3 Translate] — e.g. 000e3848-0000-0000-5df0-002d00000000 | 00000000...
game.stats.v0.ClassesComponent | 16 | 258 | Y | heap-range | [DECODED] ~ eoc::ClassesComponent [Array<ClassInfo> Classes]
game.stats.v2.DifficultyCheckComponent | 4 | 258 | Y | u32-varied | ~ eoc::DifficultyCheckComponent [[[bg3::legacy(field_0)]] HashMap<AbilityId, uint32_t> AbilityDC; [[bg3::legacy(field_40...] — e....
game.stats.v0.HealthComponent | 32 | 530 | Y | u32-ish counters | [DECODED] ~ eoc::HealthComponent [int Hp; int MaxHp; int TemporaryHp]
game.stats.v0.LevelComponent | 4 | 258 | Y | u32-varied | ~ eoc::LevelComponent [int Level] — e.g. 15 distinct, min=0 max=20
game.stats.v0.AreaLevelComponent | 4 | 1 | Y | bool-flags | ~ eoc::stats::AreaLevelComponent [int32_t Level] — e.g. values=1
game.stats.v3.StatsComponent | 36 | 258 | Y | mixed/opaque | [DECODED] ~ eoc::encumbrance::StatsComponent [[[bg3::legacy(field_0)]] int UnencumberedWeight; [[bg3::legacy(field_4)]] int Encumbere...]
game.stats.v0.UseComponent | 8 | 963 | Y | u32-ish counters PACKED? | ~ eoc::UseComponent [Array<stats::Requirement> Requirements; int Charges; int MaxCharges]
game.status.v0.IncapacitatedComponent | 24 | 38 | Y | heap-range heap-ptr | [OTHER-AGENT] ~ eoc::status::IncapacitatedComponent [uint32_t field_0; HashMap<int32_t, Array<int32_t>> field_8; uint8_t …]
game.status.v0.IndicateDarknessComponent | 1 | 1 | Y | u8-enum PACKED? | [OTHER-AGENT] ~ eoc::status::IndicateDarknessComponent (TAG: presence-only; bytes=junk) — e.g. values=240
game.status.v0.UniqueComponent | 32 | 1 | Y | heap-range | [OTHER-AGENT] ~ esv::status::UniqueComponent [HashMap<FixedString, ComponentHandle> Unique]
game.summons.v0.SummonWithStackId | 24 | 1 | N | mixed/opaque | [OTHER-AGENT] (no ~ match)
game.summons.v0.ContainerComponent | 48 | 3 | Y | mixed/opaque | [OTHER-AGENT] ~ ls::trigger::ContainerComponent [HashSet<Guid> field_0; Array<ContainerEvent> Events]
game.summons.v2.IsSummonComponent | 48 | 1 | Y | opaque(high-entropy) | [OTHER-AGENT] ~ eoc::summon::IsSummonComponent [[[bg3::legacy(Owner_M)]] EntityHandle Owner; [[bg3::legacy(field_8)]] EntityH...
game.summons.v1.Lifetime | 16 | 1 | N | heap-range | [OTHER-AGENT] ~ eoc::status::LifetimeComponent [int field_0; [[bg3::legacy(field_4)]] float Lifetime]
game.summons.v1.LifetimeComponent | 8 | 1 | Y | u32-ish counters | [OTHER-AGENT] ~ eoc::status::LifetimeComponent [int field_0; [[bg3::legacy(field_4)]] float Lifetime]
game.tadpole_tree.v0.PowerContainerComponent | 16 | 1 | Y | opaque(high-entropy) | singleton: illithid-power container (opaque 16B)
game.tadpole_tree.v0.TadpoledComponent | 1 | 7 | Y | u8-enum PACKED? | tag: character has a tadpole (byte = junk) — e.g. values=0,4,49,88
game.tadpole_tree.v1.TreeStateComponent | 8 | 7 | Y | mixed/opaque | per-character tadpole tree state (f32 + flags; heap ptrs in some rows)
game.tags.v0.VoiceComponent | 16 | 1 | Y | mixed/opaque | ~ eoc::VoiceComponent [Guid Voice]
game.tags.v0.AnubisComponent | 16 | 2061 | Y | opaque(high-entropy) | (no ~ match)
game.tags.v0.DialogComponent | 16 | 2061 | Y | opaque(high-entropy) | (no ~ match)
game.tags.v0.OsirisComponent | 16 | 2061 | Y | opaque(high-entropy) | (no ~ match)
game.tags.v0.RaceComponent | 16 | 258 | Y | heap-range | ~ eoc::RaceComponent [Guid Race]
game.templates.v0.TemplateComponent | 24 | 1677 | Y | heap-ptr +mixed | [DECODED] (no ~ match)
game.through.v0.CanSeeThroughComponent | 1 | 1673 | Y | u8-varied | ~ eoc::through::CanSeeThroughComponent (TAG: presence-only; bytes=junk) — e.g. 104 distinct, min=0 max=255
game.through.v0.CanShootThroughComponent | 1 | 1317 | Y | u8-varied PACKED? | ~ eoc::through::CanShootThroughComponent (TAG: presence-only; bytes=junk) — e.g. 162 distinct, min=0 max=255
game.through.v0.ShootThroughTypeComponent | 8 | 1677 | Y | mixed/opaque | ~ eoc::through::ShootThroughTypeComponent [uint8_t Type]
game.through.v0.CanWalkThroughComponent | 1 | 1360 | Y | u8-varied | ~ eoc::through::CanWalkThroughComponent (TAG: presence-only; bytes=junk) — e.g. 43 distinct, min=0 max=255
game.timeline.v1.ActorVisualDataComponent | 32 | 3 | Y | string-pool refs | (no ~ match) — e.g. 0b8fdd17-7ce6-4038-9d9d-49f5ddbc20be | 3773c64c-c5a9-9baf...
game.trade.v0.CanTradeComponent | 1 | 99 | Y | u8-varied | ~ eoc::trade::CanTradeComponent (TAG: presence-only; bytes=junk) — e.g. 16 distinct, min=0 max=228
game.trade.v0.CanTradeSetComponent | 1 | 99 | Y | u8-varied | (no ~ match) — e.g. 10 distinct, min=0 max=228
game.trade.v0.LegacyCanTradeProcessedComponent | 1 | 258 | Y | u8-varied | (no ~ match) — e.g. 49 distinct, min=0 max=255
game.trade.v0.PresentTraderComponent | 1 | 2 | Y | all-zero | (no ~ match)
game.triggers.v0.ContainerComponent | 32 | 5 | Y | opaque(high-entropy) | ~ ls::trigger::ContainerComponent [HashSet<Guid> field_0; Array<ContainerEvent> Events]
game.triggers.v0.InInsideOfTriggerComponent | 16 | 1677 | Y | opaque(high-entropy) | (no ~ match)
game.triggers.v0.ActiveMusicVolumeComponent | 8 | 13 | Y | mixed/opaque | (no ~ match)
game.triggers.v2.CachedLeaveEventsComponent | 16 | 1677 | Y | opaque(high-entropy) | ~ esv::trigger::CachedLeaveEventsComponent [Array<CachedLeaveEventData> Updated]
game.triggers.v0.RegisteredForTriggersComponent | 16 | 258 | Y | opaque(high-entropy) | (no ~ match)
game.triggers.v0.RegistrationSettingsComponent | 1 | 5 | Y | u8-enum PACKED? | ~ esv::trigger::RegistrationSettingsComponent [bool Registered] — e.g. values=255
game.turn_based.v1.ParticipantComponent | 8 | 1677 | Y | opaque(high-entropy) | [OTHER-AGENT] ~ eoc::combat::ParticipantComponent [EntityHandle CombatHandle; FixedString CombatGroupId; [[bg3::legac...
game.turn_based.v1.ZoneBlockReasonComponent | 1 | 258 | Y | u8-enum PACKED? | [OTHER-AGENT] ~ eoc::ftb::ZoneBlockReasonComponent [uint8_t Reason] — e.g. values=0,255
game.turn_based.v4.TurnBasedComponent | 48 | 1677 | Y | mixed/opaque | [OTHER-AGENT] ~ eoc::TurnBasedComponent [[[bg3::legacy(IsInCombat_M)]] bool IsActiveCombatTurn; [[bg3::legacy(field_A)]] bool ...
game.turn_based.v0.FTBTurnBasedComponent | 16 | 1677 | Y | mixed/opaque | [OTHER-AGENT] (no ~ match)
tutorial.v0.ProfileEventDataComponent | 32 | 1 | Y | mixed/opaque | (no ~ match)
game.unsheath.v8.StateComponent | 40 | 258 | Y | heap-range +u32-high-entropy | [OTHER-AGENT] ~ eoc::unsheath::StateComponent [[[bg3::legacy(field_0)]] EntityHandle MainHandWeapon; [[bg3::legacy(fi...
game.unsheath.v0.DefaultComponent | 16 | 55 | Y | mixed/opaque | [OTHER-AGENT] ~ esv::unsheath::DefaultComponent [int field_0; bool field_4]
game.unsheath.v0.ScriptOverrideComponent | 16 | 3 | Y | mixed/opaque | [OTHER-AGENT] ~ esv::unsheath::ScriptOverrideComponent [Array<int32_t> field_0]
game.visual.v5.GameObjectVisualComponent | 56 | 1677 | Y | string-pool refs heap-ptr +mixed | per-entity visuals: icon name {ptr,len} @24/@32, f32 scale=1.0 @40, ptr->visual GUID list @48 — e.g. 2a...
game.visual.v5.CharacterCreationTemplateOverrideComponent | 16 | 1 | Y | mixed/opaque | ~ eoc::object_visual::CharacterCreationTemplateOverrideComponent [FixedString Template]
game.v0.WeaponSetComponent | 8 | 258 | Y | mixed/opaque | ~ eoc::WeaponSetComponent [WeaponSetType WeaponSet]
game.v0.EState | 8 | 2 | N | heap-ptr | enum-value pool: u64 rows referenced by pointer from sibling components
game.body_type.v0.EBodyType | 8 | 2 | N | constant | enum-value pool: u64 rows referenced by pointer from sibling components — e.g. row=a85f2d0000000000
game.attitude.v0.EIdentityState | 8 | 1 | N | mixed/opaque | enum-value pool: u64 rows referenced by pointer from sibling components
game.camp.v1.EEndTheDayState | 8 | 1 | N | mixed/opaque | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v0.ELootableCapabilities | 8 | 2 | N | bool-flags | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v0.EActionCapabilities | 8 | 1 | N | all-zero | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v0.ERestCapabilities | 8 | 1 | N | bool-flags | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v1.EInteractionCapabilities | 8 | 7 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v1.EInteractionError | 8 | 2 | N | heap-ptr | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v0.EModifyHealthCapabilities | 8 | 1 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v1.EMovementCapabilities | 8 | 8 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v0.EMovementError | 8 | 1 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v0.EPathMovementSpeed | 8 | 1 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v0.EAwarenessCapabilities | 8 | 8 | N | heap-ptr | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v0.ESpeakingCapabilities | 8 | 3 | N | heap-ptr | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v0.ETravelCapabilities | 8 | 2 | N | heap-ptr | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v1.ETravelError | 8 | 2 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v1.EGatherAtCampError | 8 | 3 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v1.ERandomCastError | 8 | 1 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.capabilities.v0.EFleeBlock | 8 | 6 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.character.v0.ECharacterStowedOption | 8 | 2 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.character_creation.v1.ESelectorOwnerType | 8 | 5 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.character_creation.v1.EAbility | 8 | 6 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.character_creation.v1.ESkill | 8 | 14 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.character_creation.v1.EBodyShape | 8 | 2 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.identity.v0.EIdentity | 8 | 2 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.combat.v0.ECombatParticipantComponentFlags | 8 | 11 | N | u32-ish counters | (no ~ match)
game.spell.v0.ESourceType | 8 | 15 | N | u32-ish counters | [DECODED] enum-value pool: u64 rows referenced by pointer from sibling components
game.darkness.v1.EDarknessActiveSource | 8 | 3 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.darkness.v1.EObscuredState | 8 | 3 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.death.v1.EDeathType | 8 | 3 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.death.v2.TCauseType | 8 | 4 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.v0.DetachOrigin | 8 | 1 | N | u32-ish counters | (no ~ match)
game.hotbar.v2.EHotBarType | 8 | 9 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.hotbar.v0.EHotBarControllerType | 8 | 3 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.identity.v0.EIdentityState | 8 | 1 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.interrupt.v0.EInteractionType | 8 | 3 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.inventory.v0.EIsTradableType | 8 | 2 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.invisibility.v6.EInvisibilitySourceType | 8 | 2 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.item.animation.v0.EAnimationState | 8 | 2 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.multiplayer.v0.EJoinBlockType | 8 | 1 | N | all-zero | enum-value pool: u64 rows referenced by pointer from sibling components
game.relation.v0.ERelation | 8 | 4 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EChangeType | 8 | 1 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EItemTooltipChange | 8 | 2 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EIdentityState | 8 | 2 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.ECharacterFootStepsType | 8 | 6 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EBodyType | 8 | 2 | N | mixed/opaque | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EActionCapabilities | 8 | 2 | N | mixed/opaque | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EInteractionCapabilities | 8 | 2 | N | mixed/opaque | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EAwarenessCapabilities | 8 | 2 | N | bool-flags | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.ESpeakingCapabilities | 8 | 2 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.templates.v0.ETemplateHandleType | 8 | 3 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EArmorType | 8 | 4 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EAbility | 8 | 8 | N | mixed/opaque | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.size.v0.EObjectSize | 8 | 2 | N | mixed/opaque | enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EInheritanceType | 8 | 1 | N | mixed/opaque | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EAttributeFlags | 8 | 1 | N | bool-flags | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EResistanceType | 8 | 1 | N | mixed/opaque | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.shapeshift.v0.EProficiencyGroup | 8 | 1 | N | opaque(high-entropy) | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.spell.v0.ELearningStrategy | 8 | 1 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.spell.v0.EPreparationStrategy | 8 | 1 | N | opaque(high-entropy) | enum-value pool: u64 rows referenced by pointer from sibling components
game.spell.v0.EAbility | 8 | 6 | N | all-zero | enum-value pool: u64 rows referenced by pointer from sibling components
game.spell.v1.ECooldownType | 8 | 7 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.spell.v2.ESpellRequirementType | 8 | 20 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.spell.v0.ESpellSchool | 8 | 1 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.damage.v0.EDamageType | 8 | 1 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.status.v0.EIncapacitationReason | 8 | 2 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.summons.v1.EExtendedLifetime | 8 | 1 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.tadpole_tree.v1.ETadpoleTreeState | 8 | 3 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.triggers.v2.EEventSendingMode | 8 | 4 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
game.turn_based.v0.EEndTurnRequestReason | 8 | 1 | N | bool-flags | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.unsheath.v7.EPriority | 8 | 6 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.unsheath.v0.EState | 8 | 3 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.unsheath.v0.ECause | 8 | 2 | N | u32-ish counters | [OTHER-AGENT] enum-value pool: u64 rows referenced by pointer from sibling components
game.v0.EWeaponSet | 8 | 2 | N | u32-ish counters | enum-value pool: u64 rows referenced by pointer from sibling components
```
