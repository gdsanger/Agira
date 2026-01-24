# Agira Data Model (v1 – final)

Ziel:
Ein schlankes, pragmatisches Dev-/Support-System (Kigil-Prinzip) mit:
- Projekten + Items (Parent/Child + Abhängigkeiten)
- Architektur-Nodes
- GitHub-Integration (Issues + PRs)
- Releases (Versionen)
- Changes (Deployments)
- Audit-fähigem Approval
- Kommunikationshistorie (Kommentare + Mail)
- Attachments (lokaler Storage)
- Activity Stream
- KI-Integrationen

Keine Tenant-Logik, kein Scrum-Zwang, keine Rollen-Matrix.

---

## Organisation

### Properties
- id
- name
- users (reverse FK `UserOrganisation`)

---

## ItemType
Global, nicht projektbezogen.

### Properties
- id
- key
- name
- is_active (bool, default true)

---

## User
Eigene Userklasse, DjangoAuth-basiert.

### Properties
- id
- name
- username
- email
- role (ENUM: `User`, `Agent`, `Approver`)
- active (bool)
- organisations (reverse FK `UserOrganisation`)

---

## UserOrganisation
Mapping User ↔ Organisation.

### Properties
- id
- organisation (FK Organisation)
- user (FK User)
- is_primary (bool)

### Constraints
- unique(user, organisation)
- max. 1 primary pro User  
  (Partial Unique Index auf `is_primary = true`)

---

## Project
Projekt = logische Einheit + genau ein GitHub-Repo.

### Properties
- id
- name
- description (longtext, markdown)
- github_owner
- github_repo
- clients (M2M Organisation, blank=true)
- status (ENUM: `New`, `Working`, `Canceled`, `Finished`)
- sentry_dsn
- sentry_project_slug
- sentry_auth_token
- sentry_enable_auto_fetch (bool)

Relations:
- items (reverse FK Item)
- releases (reverse FK Release)
- changes (reverse FK Change)

---

## Node
Architektur-/Strukturbaum pro Projekt.

### Properties
- id
- name
- project (FK Project)
- type (ENUM: `Project`, `View`, `Entity`, `Class`, `Action`, `Report`, `Other`)
- matchkey (calculated: `type:name`)
- description (longtext, markdown)
- parent_node (FK Node, null=true)
- child_nodes (reverse FK)
- items (reverse M2M Item.nodes)

---

## Release
Version / ausgelieferter Stand.

### Properties
- id
- project (FK Project)
- name
- version (z. B. v1.0.0)
- risk (ENUM: `Low`, `Normal`, `High`, `VeryHigh`)
- risk_description (longtext)
- risk_mitigation (longtext)
- rescue_measure (longtext)
- update_date (date)
- status (ENUM: `Planned`, `Working`, `Closed`)

Relations:
- items (reverse FK Item.solution_release)
- changes (reverse FK Change.release)

---

## Change
Ein konkretes Deployment / Update.  
**Jeder Deployment-Vorgang hat genau einen Change.**

### Properties
- id
- project (FK Project)
- title
- description (longtext, markdown)
- planned_start (datetime, null=true)
- planned_end (datetime, null=true)
- executed_at (datetime, null=true)
- status (ENUM: `Draft`, `Planned`, `InProgress`, `Deployed`, `RolledBack`, `Canceled`)
- risk (ENUM: `Low`, `Normal`, `High`, `VeryHigh`)
- risk_description (longtext)
- mitigation (longtext)
- rollback_plan (longtext)
- communication_plan (longtext, null=true)
- created_at (datetime)
- updated_at (datetime)
- created_by (FK User, null=true)
- release (FK Release, null=true)

Relations:
- items (M2M Item, blank=true)
- approvals (reverse FK ChangeApproval)

Rules:
- Alle Items müssen zum selben Projekt gehören.
- Release (falls gesetzt) muss zum Projekt gehören.

---

## ChangeApproval
Minimal, audit-tauglich, ohne Rollen-Gedöns.

### Properties
- id
- change (FK Change)
- approver (FK User)
- is_required (bool, default true)
- status (ENUM: `Pending`, `Approved`, `Rejected`)
- decision_at (datetime, null=true)
- comment (text, blank=true)

Constraints:
- unique(change, approver)

Audit-Auswertung:
- Required Approvers = is_required = true
- Approved by = status = Approved

---

## Item
Arbeitsauftrag / Idee / Bug / Feature.

### Properties
- id
- created_at (datetime)
- updated_at (datetime)
- project (FK Project)
- parent (FK Item, null=true)
- title
- description (longtext, markdown)
- solution_description (longtext)
- type (FK ItemType)
- nodes (M2M Node, blank=true)
- organisation (FK Organisation, null=true)
- requester (FK User, null=true)
- assigned_to (FK User, null=true)
- status (ENUM: `Inbox`, `Backlog`, `Working`, `Testing`, `ReadyForRelease`, `Closed`)
- solution_release (FK Release, null=true)

Relations:
- children (reverse FK)
- github_items (reverse FK ExternalIssueMapping)
- comments (reverse FK ItemComment)
- attachments (via AttachmentLink)

Rules:
- parent nur im selben Projekt
- Nodes nur aus dem Projekt
- Wenn project.clients nicht leer:
  → item.organisation ∈ project.clients

---

## ItemRelation
Querverbindungen zwischen Items (nicht Parent/Child).

### Properties
- from_item (FK Item)
- to_item (FK Item)
- relation_type (ENUM: `DependOn`, `Similar`, `Related`)

Constraints:
- unique(from_item, to_item, relation_type)
- Indizes auf from_item, to_item
- Zyklusprüfung nur für DependOn (später)

---

## ExternalIssueMapping
Zuordnung zu GitHub Issues & PRs (1:n).

### Properties
- id
- item (FK Item)
- github_id (bigint, unique)
- number (Issue/PR Nummer)
- kind (ENUM: `Issue`, `PR`)
- state (string)
- html_url
- last_synced_at (datetime)

---

## ItemComment
Kommunikations- & Notizhistorie inkl. Mail.

### Properties
- id
- item (FK Item)
- created_at (datetime)
- author (FK User, null=true)
- visibility (ENUM: `Public`, `Internal`)
- kind (ENUM: `Note`, `Comment`, `EmailIn`, `EmailOut`)
- subject (string, null=true)
- body (longtext)
- body_html (longtext, null=true)
- external_from (string, null=true)
- external_to (string/json, null=true)
- message_id (string, null=true)
- in_reply_to (string, null=true)
- delivery_status (ENUM: `Draft`, `Queued`, `Sent`, `Failed`)
- sent_at (datetime, null=true)

Relations:
- attachments (via AttachmentLink)

---

## Attachment
Datei lokal, Metadaten in DB.

### Properties
- id
- project (FK Project)
- uploaded_at (datetime)
- uploaded_by (FK User, null=true)
- file (FileField, local storage)
- original_name
- content_type
- size
- sha256 (string, null=true)
- description (text, null=true)

---

## AttachmentLink
Generische Verknüpfung von Attachments.

### Properties
- id
- attachment (FK Attachment)
- target_content_type
- target_object_id
- target (GenericForeignKey)
- role (ENUM: `ProjectFile`, `ItemFile`, `CommentAttachment`)

Constraints:
- unique(attachment, target_content_type, target_object_id)

---

## Activity
Activity Stream / Audit Feed.

### Properties
- id
- target_content_type
- target_object_id
- target (GenericForeignKey)
- verb (z. B. `item.created`, `change.approved`)
- actor (FK User, null=true)
- summary (text)
- created_at (datetime)

---

## AIProvider

### Properties
- id
- name
- provider_type (ENUM: `OpenAI`, `Gemini`, `Claude`)
- api_key (encrypted)
- organization_id (OpenAI only)

---

## AIModel

### Properties
- id
- provider (FK AIProvider)
- name
- model_id
- input_price_per_1m_tokens
- output_price_per_1m_tokens
- active (bool)

---

## AIJobsHistory

### Properties
- id
- agent
- user (FK User)
- provider (FK AIProvider)
- model (FK AIModel)
- status (ENUM: `Pending`, `Completed`, `Error`)
- client_ip
- input_tokens
- output_tokens
- costs
- timestamp (datetime)
- duration_ms

---

## Configuration (Singletons)

### GitHub_Configuration
- enable_github
- github_token (encrypted)
- github_api_base_url
- default_github_owner
- github_copilot_username

### Weaviate_Configuration
- weaviate_url
- weaviate_api_key (encrypted)
- weaviate_port
- weaviate_grpc
- weaviate_timeout

### Google_PSE_Configuration
- enable_google_pse
- google_search_api_key (encrypted)
- google_search_cx

### GRAPH_API_Configuration
- graph_client_id
- graph_client_secret (encrypted)
- graph_tenant_id
- graph_default_mail_sender

### ZAMMAD_Configuration
- enable_zammad_integration
- zammad_api_url
- zammad_groups
- zammad_api_token (encrypted)
- zammad_sync_interval