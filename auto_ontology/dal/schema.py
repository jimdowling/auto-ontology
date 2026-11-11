# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The relational schema: SQLAlchemy Core table metadata, no ORM.

The store is RonDB through the MySQL protocol. On Hopsworks the tables belong
to the ontology app and are created through the platform's app-tables API by
:mod:`auto_ontology.dal.migrations`, which reads :data:`METADATA`; this file is
the single source of truth for the schema.

**Table names carry the app's prefix.** Hopsworks requires every app table to
start with the app's table prefix (``app_<app>__``), so :func:`_name` prepends
``ONTOLOGY_TABLE_PREFIX``, read once at import. The Python names stay the
upstream ones: ``s.term`` is the table, ``s.term.name`` its prefixed name, and
raw SQL must use the latter.

**NDB shapes the column types.** A table that is the child of an ``ON DELETE
CASCADE`` foreign key cannot hold TEXT or BLOB columns (NDB error 21034), so on
those tables free text is a bounded ``VARCHAR`` that :class:`Bounded` truncates
on write. Rows stay under about 14,000 bytes counted from declared sizes, and
names are ``VARCHAR(191)`` so composite unique keys fit NDB's key length.
Tables use ``utf8mb4_bin``, so equality and ``LIKE`` are case-sensitive as they
were on Postgres; ``ilike`` lowers both sides.

Four decisions shape everything downstream:

* **Containment is a parent foreign key, not an edge table.** A database owns
  its schemas, a schema its tables, a table its columns. That is what makes
  deleting a database one statement, with ``ON DELETE CASCADE`` doing the rest.
* **Ids are string uuids**, generated in Python by :func:`new_id` because
  MySQL has no ``RETURNING`` to hand a server-generated id back. Not integers:
  ids are consumed as opaque strings by the vector-store row key, the frontend's
  pipe-separated focus param, and ``model_interchange``'s ``imported_id OR id``
  match.
* **The catalog tier is prefixed ``catalog_``** — one rule that sidesteps
  ``table`` and ``column`` being reserved words and ``schema`` colliding with
  ``information_schema``, instead of three separate exceptions.
* **Association tables contain exactly one ``__``; entity tables contain none.**
  The name says which kind of table it is, and where the first endpoint's name
  ends. Both used to be guesswork: ``column_attribute_term`` could be read as
  ``column_attribute`` + ``term`` or ``column`` + ``attribute_term``, and
  nothing but familiarity separated it from the ``column_attribute`` entity
  sitting beside it.

  The separator marks the *first endpoint*, not a strict ``<source>__<target>``
  — which cannot name the self-edges (``column__join``, ``table__join``) or
  distinguish the two edges that share endpoints, ``column__has_attribute`` and
  ``column__semantic_fk``. Indexes and constraints follow their table's name, so
  ``pk_table__term`` never drifts back to the ambiguous form.
"""

from __future__ import annotations

import os
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from auto_ontology.dal.types import (
    Bounded,
    BoundedJSONText,
    JSONList,
    JSONValue,
    UTCDateTime,
    new_id,
    utcnow,
)


#: The two terminal outcomes of a semantic compilation pass, for the check
#: constraint on :data:`semantic_compilation_history` below.
#:
#: Defined here rather than in ``auto_ontology.ingestion_service.history``, which writes
#: them: they are part of the column's definition, and the module that writes
#: the values importing them from the constraint that permits them is the only
#: arrangement in which the two cannot disagree.
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"

#: Naming convention so constraints get stable, readable names that the
#: migration runner can find again. SQLAlchemy shortens a name past MySQL's 64
#: characters with a hash, which the table prefix makes common.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

METADATA = MetaData(naming_convention=NAMING_CONVENTION)

#: Hopsworks' table prefix for the ontology app, e.g. ``app_sales_ontology__``.
#: Empty in tests and local runs.
TABLE_PREFIX = os.environ.get("ONTOLOGY_TABLE_PREFIX", "")

#: String uuids, and the ids other tables store without a foreign key.
ID = String(64)
#: Names that sit in unique keys: 191 utf8mb4 characters keeps a three-name
#: composite key within NDB's key length.
NAME = String(191)
#: Short enumerations and type names.
SHORT = String(128)
#: Server-side default for creation timestamps.
_NOW = text("CURRENT_TIMESTAMP(6)")


def _name(table: str) -> str:
    return TABLE_PREFIX + table


def _table(name: str, *items: object) -> Table:
    return Table(
        _name(name),
        METADATA,
        *items,
        mysql_engine="ndbcluster",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )


def _id() -> Column:
    return Column("id", ID, primary_key=True, default=new_id)


def _imported_id() -> Column:
    """Id carried over from a model-interchange export.

    ``_resolve_entities_batch`` matches YAML ids against ``imported_id OR id``,
    so an id from a previous export can arrive as an *imported* id on a node
    whose own id is different. Non-unique: two databases can legitimately import
    the same source model.
    """
    return Column("imported_id", String(255), nullable=True)


def _certified(name: str) -> Column:
    """A human-set certification flag.

    ``NOT NULL DEFAULT false`` rather than nullable, because every read of these
    absent means false, and making that the column's job removes the coalesce
    from each caller — and, more usefully, the chance of one forgetting it.
    """
    return Column(name, Boolean, nullable=False, server_default=text("false"))


def _edited() -> tuple[Column, Column, Column, Column]:
    """When the row was inserted and when someone last edited it in the app.

    ``created`` is the database clock on insert. The migration adds the column
    without backfilling, so a row that already existed stays null rather than
    claiming it was created the day the column appeared.

    ``modified`` and ``modified_by`` stay null until a person saves an edit.
    Compilation rewrites descriptions on its own and does not count: the panel's
    Last Modified is that save. ``modified_by`` is a Hopsworks username, null
    when the request carried no identity, which the page reads as Auto Generated.
    """
    return (
        Column("created", UTCDateTime, nullable=True, server_default=_NOW),
        Column("modified", UTCDateTime, nullable=True),
        Column("created_by", ID, nullable=True),
        Column("modified_by", ID, nullable=True),
    )


def _owner_id() -> Column:
    """The account or group that owns the row, or null when nobody does.

    Stored on a database, a schema, a table, a term, and a sql attribute. The
    catalog page edits it on a table, and the glossary page edits it on a
    term. A column shows that table's owner and a column attribute shows its
    term's owner; neither stores one of its own. A sql attribute keeps the
    column, and its page shows the term's owner. The edit check for a column,
    a column attribute, and a sql attribute does not read an owner on that
    row. A database and a schema keep the column, and the page does not edit
    it there. One column holds either id: a Hopsworks username or a
    ``user_group.id``. Neither can be a foreign key, because the accounts live
    in Hopsworks and one reference cannot name both. An empty write clears it.
    A removed member or group leaves the id behind, which reads as unassigned.
    """
    return Column("owner_id", ID, nullable=True)


# ---------------------------------------------------------------------------
# Catalog tier — Database -> Schema -> Table -> Column
# ---------------------------------------------------------------------------

catalog_database = _table(
    "catalog_database",
    _id(),
    Column("name", NAME, nullable=False, unique=True),
    # The ontology source this database came from: the Hopsworks data source
    # name and its filters, never credentials. Hopsworks resolves those per
    # caller, so nothing secret is stored here.
    Column("connection", JSONValue, nullable=True),
    Column("dialect", SHORT, nullable=True),
    # A database and a schema each carry a curated description, as tables and
    # columns do. Without them `patch_catalog_node` silently dropped the write
    # and still answered 200, so the UI reported success and the text was gone
    # on reload.
    Column("description", Text, nullable=True),
    _certified("description_certified"),
    _imported_id(),
    _owner_id(),
    Column("created", UTCDateTime, server_default=_NOW),
    Column("pulled", UTCDateTime, nullable=True),
)

catalog_schema = _table(
    "catalog_schema",
    _id(),
    Column(
        "database_id",
        ID,
        ForeignKey(catalog_database.c.id, ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", NAME, nullable=False),
    Column("description", Bounded(2000), nullable=True),
    _certified("description_certified"),
    _imported_id(),
    _owner_id(),
    UniqueConstraint("database_id", "name", name="uq_catalog_schema_database_name"),
)


catalog_table = _table(
    "catalog_table",
    _id(),
    Column(
        "schema_id",
        ID,
        ForeignKey(catalog_schema.c.id, ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", NAME, nullable=False),
    Column("description", Bounded(1500), nullable=True),
    # Set from the UI's certification checkbox, via patch_catalog_node. Easy to
    # miss, because nothing in the ingest ever writes it
    # -- it only appears once a human certifies a description. Without the
    # column the PATCH still returns 200 and the checkbox still ticks; the flag
    # is simply dropped on the way in and reads back false forever.
    _certified("description_certified"),
    _owner_id(),
    # Primary key column names. A JSON list rather than a join table -- nothing
    # ever queries "which tables have this pk column", and a join table would
    # make every read a second query.
    Column("pk", JSONList(1000), nullable=True),
    Column("table_type", SHORT, nullable=True),
    # Promoted by semantic compilation when a table's row grain is an
    # association between entity roles. Compilation deliberately never clears
    # the flag: a later uncertain LLM response must not erase prior evidence.
    Column("is_junction_table", Boolean, nullable=False, server_default=text("false")),
    _imported_id(),
    UniqueConstraint("schema_id", "name", name="uq_catalog_table_schema_name"),
)

catalog_column = _table(
    "catalog_column",
    _id(),
    Column(
        "table_id",
        ID,
        ForeignKey(catalog_table.c.id, ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", NAME, nullable=False),
    Column("description", Bounded(1500), nullable=True),
    # As on catalog_table: written only by the UI's certification checkbox.
    _certified("description_certified"),
    Column("data_type", Bounded(512), nullable=True),
    # A JSON string, read back as a string by callers. Bounded like the other
    # text on a cascade child, but shortened value by value so it stays valid
    # JSON (see BoundedJSONText).
    Column("sample_values", BoundedJSONText(800), nullable=True),
    # How the values are *written*, not what they are: 'YYMMDD', 'YYYY-MM-DD'.
    # Generic storage notation despite only date inference filling it today
    # (`auto_ontology.semantic.date_format`) -- an address or id profiler would write the
    # same field. `data_type`/`name`/`description` say what the values mean.
    #
    # It exists because date columns are held out of sample-value profiling, so
    # nothing else in the prompt tells the model what form to compare against:
    # `950324` and `1995-03-24` are the same day and share no predicate, and a
    # wrong guess yields SQL that runs, returns nothing, and looks right.
    Column("format", String(64), nullable=True),
    Column("is_unique", Boolean, nullable=True),
    # A real Boolean. It used to hold the *strings* `information_schema`
    # reports, 'YES' and 'NO', which read back as truthy either way -- so
    # `bool(stored)` was True for every column and every export claimed the
    # whole catalog was nullable. Connectors now convert at their own edge
    # (see `auto_ontology.connectors.base.SQLDatabase.get_columns`) and NULL still means
    # "the connector could not determine it", which callers treat as nullable.
    Column("is_nullable", Boolean, nullable=True),
    # A genuine integer, despite the parser handing the write path a string --
    # something coerces on the way in.
    Column("ordinal_position", Integer, nullable=True),
    # Set only after automatic PII classification completes. Tag edits are
    # deliberately independent: removing an automatically assigned PII tag is
    # a user override and must not make the next ingest add it back.
    Column("pii_processed", Boolean, nullable=False, server_default=text("false")),
    _imported_id(),
    UniqueConstraint("table_id", "name", name="uq_catalog_column_table_name"),
)

# FOREIGN_KEY: Column -> Column.
column__foreign_key = _table(
    "column__foreign_key",
    Column(
        "source_column_id",
        ID,
        ForeignKey(catalog_column.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "target_column_id",
        ID,
        ForeignKey(catalog_column.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    # Stamped by every ingest, then used to delete the keys this run did not
    # see -- the source database may have dropped a constraint. Without it
    # there is no way to tell a removed foreign key from one simply not
    # re-asserted, and stale keys would accumulate forever.
    Column("last_seen", UTCDateTime, nullable=True),
)


# JOIN / UNION: Column <-> Column, carrying the statements that observed them.
#
# Distinct from `table__join` below, and both are real. This one is written by
# **query** ingestion -- `sql_parse` emits one entry per observed join
# condition, so `refs` accumulates `"<sql id>|<condition>"` strings as more
# statements are seen. `table__join` is written only by a model import and
# carries the join's *columns*; nothing writes both.
#
# `refs` is a JSON list that grows rather than a row per reference, because that
# is what the readers expect. The table is a cascade child, so the list is a
# bounded VARCHAR that keeps the newest references when it fills.
def _column_pair_edge(name: str) -> Table:
    return _table(
        name,
        Column(
            "source_column_id",
            ID,
            ForeignKey(catalog_column.c.id, ondelete="CASCADE"),
            primary_key=True,
        ),
        Column(
            "target_column_id",
            ID,
            ForeignKey(catalog_column.c.id, ondelete="CASCADE"),
            primary_key=True,
        ),
        Column(
            "refs", JSONList(3000, keep="last"), nullable=False, server_default="[]"
        ),
    )


column__join = _column_pair_edge("column__join")
column__union = _column_pair_edge("column__union")


# JOIN: Table -> Table, carrying the columns that join them.
table__join = _table(
    "table__join",
    Column(
        "source_table_id",
        ID,
        ForeignKey(catalog_table.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "target_table_id",
        ID,
        ForeignKey(catalog_table.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("join_columns", JSONValue(3000), nullable=True),
)

# ---------------------------------------------------------------------------
# SQL statements and their table references
# ---------------------------------------------------------------------------

sql_query = _table(
    "sql_query",
    _id(),
    Column("sql_full_query", MEDIUMTEXT, nullable=False),
    Column("query_count", Integer, nullable=False, server_default=text("0")),
    Column("created", UTCDateTime, server_default=_NOW),
    Column("last_seen", UTCDateTime, nullable=True),
    # How many times this statement has been observed, all time. The graph also
    # carried a `count_{month}_{year}` property per month, which is not
    # reproduced: no reader has ever been able to parse those names (they are
    # matched against `count_monthly_YYYY_MM`), so they hold no information
    # anything can use. See DECISIONS.md record 007.
    Column("total_counter", Integer, nullable=False, server_default=text("0")),
    Column("last_query_timestamp", UTCDateTime, nullable=True),
    # Structural fingerprint, used to pre-filter candidates before the
    # expensive sqlglot comparison in query deduplication.
    Column("nodes_count", Integer, nullable=True),
    Column("join_count", Integer, nullable=False, server_default=text("0")),
    Column("union_count", Integer, nullable=False, server_default=text("0")),
    # model_interchange matches a Sql node by its *text*
    # (match_props={"sql_full_query": sql}). Statement text can exceed the btree
    # key limit, so the uniqueness is enforced on a stored md5 of it.
    Column(
        "sql_hash",
        String(32),
        Computed("md5(sql_full_query)", persisted=True),
        nullable=False,
    ),
    UniqueConstraint("sql_hash", name="uq_sql_query_text_md5"),
)

# SQL: Sql -> Table. An association, because one statement references many
# tables and one table is referenced by many statements.
sql_query__table = _table(
    "sql_query__table",
    Column(
        "sql_query_id",
        ID,
        ForeignKey(sql_query.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "table_id",
        ID,
        ForeignKey(catalog_table.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
)

# SQL: Sql -> Column. The same relationship type, pointing at the leaf columns a
# statement selects. Two tables rather than one polymorphic association, because
# the two are always read separately -- `load_sqls_to_tables` returns tables and
# columns as distinct lists, and query deduplication compares them as distinct
# sets.
sql_query__column = _table(
    "sql_query__column",
    Column(
        "sql_query_id",
        ID,
        ForeignKey(sql_query.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "column_id",
        ID,
        ForeignKey(catalog_column.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
)

# ---------------------------------------------------------------------------
# Semantic tier
# ---------------------------------------------------------------------------

term = _table(
    "term",
    _id(),
    Column("name", NAME, nullable=False),
    Column("description", Text, nullable=True),
    Column("source", SHORT, nullable=False, server_default=text("'semantic'")),
    Column("synonyms", JSONList(), nullable=True),
    _certified("name_certified"),
    _certified("description_certified"),
    _owner_id(),
    *_edited(),
    _imported_id(),
    UniqueConstraint("name", "source", name="uq_term_name_source"),
)

# REPRESENTS: Table -> Term.
table__term = _table(
    "table__term",
    Column(
        "table_id",
        ID,
        ForeignKey(catalog_table.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("term_id", ID, ForeignKey(term.c.id, ondelete="CASCADE"), primary_key=True),
)

column_attribute = _table(
    "column_attribute",
    _id(),
    Column("name", NAME, nullable=False),
    Column("description", Text, nullable=True),
    Column("datatype", String(512), nullable=True),
    Column("source", SHORT, nullable=False, server_default=text("'semantic'")),
    Column("source_column", NAME, nullable=False),
    Column("term_name", NAME, nullable=False),
    # Deliberately NOT a foreign key, and deliberately not nullable.
    # ``_import_column_attributes`` writes '' when the column is not in the
    # document, and this is compared as a plain string in
    # `ca.table_id IN $table_ids`. An FK here would reject valid imports.
    Column("table_id", ID, nullable=False),
    Column("certified", Boolean, nullable=False, server_default=text("false")),
    Column("description_suggestion", Text, nullable=True),
    # Set once PII propagation from the attribute's columns has handled it.
    # Like `catalog_column.pii_processed`, tag edits are independent of it:
    # removing an automatically assigned PII tag is a user override and must not
    # make the next pass add it back. Taking PII off the owning column (or an
    # expression rewrite that leaves every tagged column) clears this so a
    # later tag can still propagate.
    Column("pii_processed", Boolean, nullable=False, server_default=text("false")),
    *_edited(),
    _imported_id(),
    # The 5-part merge key, exactly as merge_column_attribute matches on.
    UniqueConstraint(
        "name",
        "source_column",
        "term_name",
        "table_id",
        "source",
        name="uq_column_attribute_merge_key",
    ),
)

# PROPERTY_OF: ColumnAttribute -> Term.
#
# An edge table for what is really a one-to-many: the composite primary key only
# forbids the same pair twice, so it is `UNIQUE(attribute_id)` below that holds
# the rule the readers rely on -- **one Term per attribute**. Before it, the rule
# lived only in `link_to_term`, which deletes any other link before inserting,
# and every read that resolved an attribute's Term had to defend against a write
# path that forgot to.
column_attribute__term = _table(
    "column_attribute__term",
    Column(
        "attribute_id",
        ID,
        ForeignKey(column_attribute.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("term_id", ID, ForeignKey(term.c.id, ondelete="CASCADE"), primary_key=True),
    UniqueConstraint("attribute_id"),
)

# HAS_ATTRIBUTE and SEMANTIC_FK both run Column -> ColumnAttribute, but they
# assert different things and get their own tables rather than one table with a
# `kind` discriminator:
#
#   HAS_ATTRIBUTE  this column *is* an instance of the attribute
#   SEMANTIC_FK    this column *references* the attribute, which describes a
#                  column on another table
#
# Their cardinality already differs -- `resolve_semantic_fks` treats a column as
# unlinked when it has no SEMANTIC_FK, so at most one is expected, whereas a
# column can carry several attributes -- and a discriminator in the primary key
# makes any constraint that applies to only one of them impossible to express.
column__has_attribute = _table(
    "column__has_attribute",
    Column(
        "column_id",
        ID,
        ForeignKey(catalog_column.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "attribute_id",
        ID,
        ForeignKey(column_attribute.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
)

column__semantic_fk = _table(
    "column__semantic_fk",
    Column(
        "column_id",
        ID,
        ForeignKey(catalog_column.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "attribute_id",
        ID,
        ForeignKey(column_attribute.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "use_in_join_paths",
        Boolean,
        nullable=False,
        server_default=text("true"),
    ),
)

sql_attribute = _table(
    "sql_attribute",
    _id(),
    Column("name", NAME, nullable=False, unique=True),
    Column("description", Text, nullable=True),
    Column("expression", Text, nullable=True),
    Column("source", SHORT, nullable=True),
    Column("certified", Boolean, nullable=False, server_default=text("false")),
    _owner_id(),
    Column("description_suggestion", Text, nullable=True),
    # Set once PII propagation from the attribute's columns has handled it.
    # Like `catalog_column.pii_processed`, tag edits are independent of it:
    # removing an automatically assigned PII tag is a user override and must not
    # make the next pass add it back. An expression rewrite that no longer
    # reads a tagged column is the exception: the tag is taken off and this
    # flag cleared so a later tag on one of the new columns can still propagate.
    Column("pii_processed", Boolean, nullable=False, server_default=text("false")),
    *_edited(),
    _imported_id(),
    CheckConstraint(
        "source IS NULL OR source IN ('manual', 'sql', 'table', 'bridgeTable')",
        name="source_value",
    ),
)

# PROPERTY_OF: SqlAttribute -> Term.
#
# `UNIQUE(attribute_id)` for the reason given on `column_attribute__term`: the
# two kinds of attribute are properties of exactly one Term in the same sense,
# and the pages that list them read both the same way. A SqlAttribute reached
# through a CustomAnalysis has no row here at all, which is a different thing
# from having two.
sql_attribute__term = _table(
    "sql_attribute__term",
    Column(
        "attribute_id",
        ID,
        ForeignKey(sql_attribute.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("term_id", ID, ForeignKey(term.c.id, ondelete="CASCADE"), primary_key=True),
    UniqueConstraint("attribute_id"),
)

# HAS_SQL: SqlAttribute -> Sql.
sql_attribute__sql = _table(
    "sql_attribute__sql",
    Column(
        "attribute_id",
        ID,
        ForeignKey(sql_attribute.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "sql_query_id",
        ID,
        ForeignKey(sql_query.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
)

custom_analysis = _table(
    "custom_analysis",
    _id(),
    Column("name", NAME, nullable=False, unique=True),
    Column("description", Text, nullable=True),
    _imported_id(),
)

# HAS_SQL: CustomAnalysis -> Sql.
custom_analysis__sql = _table(
    "custom_analysis__sql",
    Column(
        "analysis_id",
        ID,
        ForeignKey(custom_analysis.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "sql_query_id",
        ID,
        ForeignKey(sql_query.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
)

# Never attached to a database, which is why a *scoped* semantic reset does not
# reach these -- see `reset.delete_semantic_layer`.
pql_analysis = _table(
    "pql_analysis",
    _id(),
    Column("name", NAME, nullable=False),
    Column("description", Text, nullable=True),
    Column("pql", Text, nullable=True),
    _imported_id(),
)

# Declared in auto_ontology/semantic/constants.py and referenced by reset.py's
# _SEMANTIC_LABELS, but never written by Auto Ontology today. Created so the reset
# cascade has something to point at and so a future writer needs no migration.
text_attribute = _table(
    "text_attribute",
    _id(),
    Column("name", NAME, nullable=False),
    Column("description", Text, nullable=True),
    _imported_id(),
)

analysis = _table(
    "analysis",
    _id(),
    Column("name", NAME, nullable=False),
    Column("description", Text, nullable=True),
    _imported_id(),
)

# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

zone = _table(
    "zone",
    _id(),
    # Deliberately **not** unique. The rule the application enforces is neither
    # what a plain UNIQUE gives you nor a stricter version of it:
    #
    #   * it is case-insensitive on the *trimmed* name, so a UNIQUE column would
    #     admit "Sales" alongside "sales", which the application rejects; and
    #   * it is scoped to zones sharing a database with the zone's items, so a
    #     UNIQUE column would reject the same zone name in two unrelated
    #     databases, which the application allows.
    #
    # A constraint that is wrong in both directions is worse than none. The
    # check stays in application code, exactly as today. Making it a database
    # constraint would mean a partial index on `lower(trim(name))` *per
    # database*, which zone membership -- being many-to-many through
    # zone_target -- cannot express.
    Column("name", NAME, nullable=False),
    Column("description", Text, nullable=True),
    Column("color", SHORT, nullable=True),
    # A disabled zone still exists and is still administrable; it just grants
    # nothing. A boolean rather than a separate table so every read says
    # `enabled` once instead of unioning two sources.
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
)

# ZONE_OF is polymorphic: a zone can target a Database, a Schema or a Table.
# Three nullable FKs, exactly one set per row (the DAL's writes enforce it; NDB
# has no CHECK to), beat a (kind, id) pair because they keep real
# referential integrity and lets a deleted table remove its zone membership by
# cascade -- a (kind, id) pair cannot have an FK at all, and would leave
# dangling grants behind, which is an access-control bug rather than untidiness.
zone_target = _table(
    "zone_target",
    _id(),
    Column("zone_id", ID, ForeignKey(zone.c.id, ondelete="CASCADE"), nullable=False),
    Column(
        "database_id",
        ID,
        ForeignKey(catalog_database.c.id, ondelete="CASCADE"),
        nullable=True,
    ),
    Column(
        "schema_id",
        ID,
        ForeignKey(catalog_schema.c.id, ondelete="CASCADE"),
        nullable=True,
    ),
    Column(
        "table_id",
        ID,
        ForeignKey(catalog_table.c.id, ondelete="CASCADE"),
        nullable=True,
    ),
)

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

tag = _table(
    "tag",
    _id(),
    # Uniqueness is `uq_tag_name_lower`, not a UNIQUE on this column: the rule
    # the application enforces is case-insensitive on the *trimmed* name, and a
    # plain UNIQUE would admit "PII" beside "pii".
    Column("name", NAME, nullable=False),
    Column(
        "created",
        UTCDateTime,
        nullable=False,
        server_default=_NOW,
    ),
    # Set by the database on insert and by SQLAlchemy's ``onupdate`` on every
    # UPDATE the DAL issues, so no caller has to remember to touch it -- a
    # rename advances it without `update_tag` naming this column at all. Equal
    # to ``created`` until a tag is first renamed, which is why the settings
    # page renders it as "Never" rather than repeating the creation date as if
    # the tag had been changed.
    Column(
        "modified",
        UTCDateTime,
        nullable=False,
        server_default=_NOW,
        onupdate=utcnow,
    ),
    # Who created the tag and who last edited it, as Hopsworks usernames.
    #
    # Deliberately not foreign keys. The accounts live in Hopsworks, so there is
    # nothing here to reference; and a tag must outlive the member who made it,
    # which a FK with any `ondelete` would either forbid or quietly rewrite.
    #
    # Nullable because jobs write tags with no caller identity (rule replays,
    # PII detection). The settings page reads that as "Auto Generated" -- with
    # no account to name, the deployment is what is left -- rather than
    # inventing an author.
    #
    # `modified_by` is additionally null for a tag nothing has edited yet, which
    # is the same fact `modified == created` states -- the page renders those
    # two together as an edit that never happened.
    #
    # Either may also hold an id no account answers to, since these are not
    # foreign keys and an account can be deleted; the page reads that the same
    # way it reads a null, having nobody to name either way.
    Column("created_by", ID, nullable=True),
    Column("modified_by", ID, nullable=True),
    # The tag name rule as a constraint rather than a convention. Unlike
    # `zone.name` -- whose rule is scoped to the databases a zone's items live
    # in, which no index can express -- a tag name is unique across the whole
    # deployment, so an expression index states the rule exactly. It also closes
    # the window between the DAL's duplicate check and its insert, which two
    # concurrent creates of the same name would otherwise slip through.
    #
    # NDB has no expression indexes, so the trimmed, lowered name is a stored
    # generated column with a plain unique key.
    Column(
        "name_key",
        NAME,
        Computed("lower(trim(name))", persisted=True),
        nullable=False,
    ),
    UniqueConstraint("name_key", name="uq_tag_name_lower"),
)

# TAGGED is polymorphic: a tag can label a Term, a Table, a Column, a
# ColumnAttribute or a SqlAttribute. Same nullable-FKs, exactly-one-set shape as
# `zone_target`, and for the same reason -- a (kind, id) pair can carry no
# foreign key, so deleting a column would leave a row pointing at nothing and
# the tag's page would list objects that no longer exist. Here the cascade
# removes the label with the thing it labelled.
#
# Databases and Schemas are deliberately absent. A tag is applied to the objects
# a query names, and the two container tiers already reach their contents
# through `zone_target`, which is what scopes access.
tag_target = _table(
    "tag_target",
    _id(),
    Column("tag_id", ID, ForeignKey(tag.c.id, ondelete="CASCADE"), nullable=False),
    Column(
        "term_id",
        ID,
        ForeignKey(term.c.id, ondelete="CASCADE"),
        nullable=True,
    ),
    Column(
        "table_id",
        ID,
        ForeignKey(catalog_table.c.id, ondelete="CASCADE"),
        nullable=True,
    ),
    Column(
        "column_id",
        ID,
        ForeignKey(catalog_column.c.id, ondelete="CASCADE"),
        nullable=True,
    ),
    Column(
        "column_attribute_id",
        ID,
        ForeignKey(column_attribute.c.id, ondelete="CASCADE"),
        nullable=True,
    ),
    Column(
        "sql_attribute_id",
        ID,
        ForeignKey(sql_attribute.c.id, ondelete="CASCADE"),
        nullable=True,
    ),
    # When the label was applied, for the "Tagged" column on the tag's page.
    Column(
        "tagged",
        UTCDateTime,
        nullable=False,
        server_default=_NOW,
    ),
    # Who applied it, for the "Tagged By" column beside it. A Hopsworks username
    # from the proxy's signed identity, and not a foreign key -- the same
    # arrangement as `tag.created_by`.
    #
    # Null for a label a rule applied, where `rule_id` names the source
    # instead; for one the deployment applied itself, which is what an attach
    # carrying no identity records; and for a row written before this column
    # existed. The page reads the last two the same way, as "Auto Generated" --
    # with no account and no rule claiming a label, the deployment is what is
    # left, and an older row is a label nobody ever claimed either.
    Column("tagged_by", ID, nullable=True),
    # The rule that applied it, when a rule did rather than a person. Null for a
    # hand-applied label, and the two are exclusive: `tagged_by` is the account
    # that clicked, `rule_id` the rule that matched.
    #
    # `ON DELETE CASCADE`, so deleting a rule takes back what it labelled. A
    # rule-applied tag is the rule still holding, not a fact of its own -- it is
    # re-applied as the catalog grows, and would otherwise outlive the only
    # thing that could explain it.
    #
    # A caller who wants the labels to outlive the rule anyway says so, and
    # `rules.delete_rule` clears this column before deleting -- writing the
    # rule's author into `tagged_by` as it goes, so the label reads as that
    # person's rather than as nobody's -- and the cascade then has nothing of
    # the rule's to take. That is a decision at the call site rather than a
    # weaker constraint here: while a rule exists, a label naming it is the
    # rule's.
    #
    # A one-per-(tag, object) row, so a rule cannot re-label what a person
    # already labelled by hand, or the other way about: whichever came first
    # keeps the row, and the unique constraints below absorb the second write.
    #
    # The target is named as a string because `rule` is declared further down
    # this module -- the tables read in tag order, and a rule is a later idea
    # than a tag.
    Column(
        "rule_id",
        ID,
        ForeignKey(_name("rule") + ".id", ondelete="CASCADE"),
        nullable=True,
    ),
    # One row per (tag, object), as one constraint per target column rather than
    # one across all of them. That works *because* unique keys treat NULLs as
    # distinct: the columns that do not apply to a row are null, so those
    # constraints never collide, while the one that does is enforced. A single
    # UNIQUE over every column would enforce nothing at all, for the same reason.
    #
    # Each also gives a btree led by `tag_id`, which is the read behind a tag's
    # page -- "the objects carrying this tag" -- so no separate index on `tag_id`
    # is needed. The reverse read, "the tags on this object", leads with the
    # target column instead and is served by the indexes declared below.
    UniqueConstraint("tag_id", "term_id", name="uq_tag_target_tag_id_term_id"),
    UniqueConstraint("tag_id", "table_id", name="uq_tag_target_tag_id_table_id"),
    UniqueConstraint("tag_id", "column_id", name="uq_tag_target_tag_id_column_id"),
    UniqueConstraint(
        "tag_id",
        "column_attribute_id",
        name="uq_tag_target_tag_id_column_attribute_id",
    ),
    UniqueConstraint(
        "tag_id", "sql_attribute_id", name="uq_tag_target_tag_id_sql_attribute_id"
    ),
)

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

# A rule is a saved global search plus the tags to apply to everything it
# matches. The three search columns are what the rule *replays*, so they are
# spelled the way `/search/global-search` takes the request rather than
# decomposed further -- a rule that cannot be handed back to the search is a
# rule that never reproduces what it was created from.
rule = _table(
    "rule",
    _id(),
    # Uniqueness is `uq_rule_name_lower`, below, as a tag's is: the name is how
    # the settings list refers to a rule, so two rules answering to one name
    # leave a reader unable to say which one they are about to delete -- and a
    # delete takes back everything that rule labelled.
    Column("name", NAME, nullable=False),
    Column("search_term", Text, nullable=False),
    # `contains` is the only match global search implements today, so the
    # default is the whole vocabulary. Deliberately no CHECK constraint pinning
    # it: the permitted set belongs to the search, which validates it in
    # `auto_ontology/server/rules/router.py`, and a constraint here would make adding a
    # match option a schema migration.
    Column(
        "text_match_option", SHORT, nullable=False, server_default=text("'contains'")
    ),
    # The search filters, stored whole. JSON rather than a column each because
    # this is one value that travels together -- it is written by the create and
    # read back to be handed to the search, never filtered or joined on -- and
    # because `GlobalSearchFilters` gains fields as the search does, which would
    # otherwise be a migration per flag.
    #
    # Only the filters a caller sent land here: the route dumps them with
    # `exclude_none`, so a rule saved from the search's All tab has no `objects`
    # key rather than a null one. A read fills the defaults back in, so the API
    # answers the same shape either way.
    Column("filters", JSONValue, nullable=False, default=dict),
    Column(
        "created",
        UTCDateTime,
        nullable=False,
        server_default=_NOW,
    ),
    # Advanced by `onupdate` on every UPDATE the DAL issues, as `tag.modified`
    # is, so it is the last edit rather than the last one somebody remembered to
    # record.
    Column(
        "modified",
        UTCDateTime,
        nullable=False,
        server_default=_NOW,
        onupdate=utcnow,
    ),
    # NOT NULL, unlike `tag.created_by`, and not a foreign key for the same
    # reasons that column is not: the accounts live in Hopsworks, and a rule
    # must outlive the member who saved it.
    #
    # Required because the route refuses a create it cannot attribute -- a rule
    # goes on labelling the catalog long after it was saved, so "nobody" is not
    # an author it may record.
    Column("created_by", ID, nullable=False),
    # Who last renamed the rule, as `tag.modified_by` records for a tag.
    #
    # Nullable, unlike `created_by`, and for a reason `created_by` cannot have:
    # a rule that nobody has edited has no editor, which is the same fact as
    # `modified == created`. It is set on every rename, including one carrying
    # no identity -- leaving the previous editor would credit this edit to them.
    Column("modified_by", ID, nullable=True),
    # Case- and whitespace-insensitive uniqueness on the name, spelled exactly
    # as `uq_tag_name_lower` is and for the reasons given there: an expression
    # index states the rule the DAL checks, and closes the window between that
    # check and the write which two concurrent creates would slip through.
    Column(
        "name_key",
        NAME,
        Computed("lower(trim(name))", persisted=True),
        nullable=False,
    ),
    UniqueConstraint("name_key", name="uq_rule_name_lower"),
)

# The tags a rule applies. A link table rather than a list on `rule` so a tag
# deleted from the vocabulary leaves the rules that used it by cascade, instead
# of leaving them applying an id that no longer names anything.
rule__tag = _table(
    "rule__tag",
    Column(
        "rule_id",
        ID,
        ForeignKey(rule.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        ID,
        ForeignKey(tag.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    # The order the tags were picked in, so a rule reads back as it was written.
    # The composite primary key orders by id, which is not that.
    #
    # The id and the position are the whole of what this table has to say. A
    # tag's own columns are the `tag` table's, read through the foreign key on
    # every read, so a renamed tag reads back renamed here and no copy of it
    # can go stale beside the original.
    Column("position", Integer, nullable=False),
)

# ---------------------------------------------------------------------------
# Service bookkeeping
# ---------------------------------------------------------------------------

# One row per semantic compilation pass, written by the ingestion service (see
# `auto_ontology.ingestion_service.history`) and read back by the settings page.

semantic_compilation_history = _table(
    "semantic_compilation_history",
    # An auto-increment integer, unlike the string uuids everywhere else here: rows are appended
    # in time order by one writer and read back "most recent first", which an
    # ascending integer answers directly.
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("started_at", UTCDateTime, nullable=False),
    # NULL until the pass reaches a terminal outcome -- which it never does if
    # it was stopped, disabled mid-run, or killed. See `history.py` on why an
    # unfinished pass is left this way rather than given an "aborted" status.
    Column("finished_at", UTCDateTime, nullable=True),
    Column("status", SHORT, nullable=True),
    # Where a running pass is, for the settings page: Hopsworks reports a job's
    # progress from its pod state only, so the job writes its own here.
    Column("stage", SHORT, nullable=True),
    Column("tables_done", Integer, nullable=True),
    Column("tables_total", Integer, nullable=True),
    CheckConstraint(
        f"status IS NULL OR status IN ('{RUN_SUCCEEDED}', '{RUN_FAILED}')",
        name="status_value",
    ),
)


# ---------------------------------------------------------------------------
# User groups
# ---------------------------------------------------------------------------
#
# Groups and zones are not exposed on Hopsworks, where project roles decide who
# may do what. Their tables stay, empty, so the upstream DAL code that scopes by
# them keeps working unchanged; nothing on Hopsworks writes them.


class GroupRole(StrEnum):
    """The two roles an account and a group share. A group does not invent a third."""

    ADMIN = "admin"
    VIEWER = "viewer"


#: The only roles a group can carry.
GROUP_ROLE_ADMIN = GroupRole.ADMIN
GROUP_ROLE_VIEWER = GroupRole.VIEWER

user_group = _table(
    "user_group",
    _id(),
    # Unique case-insensitively on the trimmed name, across the deployment.
    # Unlike ``zone.name`` — whose rule is per database, which no index can
    # express — a group name is global, so the expression index states it
    # exactly and closes the window between the DAL's check and its insert.
    # The key is a stored generated column, as ``uq_tag_name_lower`` is.
    Column("name", NAME, nullable=False),
    Column("description", Text, nullable=True),
    Column("color", SHORT, nullable=False),
    Column("role", SHORT, nullable=False),
    CheckConstraint(
        f"role IN ('{GROUP_ROLE_ADMIN}', '{GROUP_ROLE_VIEWER}')",
        name="role_value",
    ),
    Column(
        "created",
        UTCDateTime,
        nullable=False,
        server_default=_NOW,
    ),
    Column(
        "name_key",
        NAME,
        Computed("lower(trim(name))", persisted=True),
        nullable=False,
    ),
    UniqueConstraint("name_key", name="uq_user_group_name_lower"),
)

# Who belongs to a group. The composite primary key leads with ``group_id``,
# which answers "the members of this group". The reverse — "the groups of this
# account" — is ``ix_user_group__member_user_id`` below.
user_group__member = _table(
    "user_group__member",
    Column(
        "group_id",
        ID,
        ForeignKey(user_group.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("user_id", ID, primary_key=True),
)


# ---------------------------------------------------------------------------
# Vector bookkeeping
# ---------------------------------------------------------------------------

# What each embedding feature group holds. The vector index can only be searched
# by similarity, so this is how a reset finds a database's vectors to delete,
# and how reconciliation finds outstanding work: an ontology row with no entry
# here, or whose current text hashes differently, has not been embedded.
vector_row = _table(
    "vector_row",
    Column("collection", SHORT, primary_key=True),
    Column("id", ID, primary_key=True),
    Column("database_name", NAME, nullable=True),
    Column("label", SHORT, nullable=True),
    Column("text_hash", String(64), nullable=False),
    Column("written_at", UTCDateTime, nullable=False, server_default=_NOW),
)

# ---------------------------------------------------------------------------
# Chat and settings (owned by Prisma upstream)
# ---------------------------------------------------------------------------

conversations = _table(
    "conversations",
    _id(),
    # A Hopsworks username: a conversation belongs to the member who started it.
    Column("user_id", ID, nullable=False),
    Column("title", String(255), nullable=False, server_default=""),
    Column("created_at", UTCDateTime, nullable=False, server_default=_NOW),
    Column(
        "updated_at", UTCDateTime, nullable=False, server_default=_NOW, onupdate=utcnow
    ),
)

# No foreign key to `conversations`: the turns hold long text, and NDB refuses
# TEXT on the child of a cascading foreign key, so the DAL deletes a
# conversation's messages itself.
messages = _table(
    "messages",
    _id(),
    Column("conversation_id", ID, nullable=False),
    Column("role", SHORT, nullable=False),
    Column("content", MEDIUMTEXT, nullable=False, default=""),
    Column("sql_code", Text, nullable=True),
    Column("sql_response", MEDIUMTEXT, nullable=True),
    Column("created_at", UTCDateTime, nullable=False, server_default=_NOW),
)

prompts = _table(
    "prompts",
    _id(),
    Column("content", Text, nullable=False, default=""),
)

configurations = _table(
    "configurations",
    Column("key", NAME, primary_key=True),
    Column("value", Text, nullable=False),
    Column(
        "updated_at", UTCDateTime, nullable=False, server_default=_NOW, onupdate=utcnow
    ),
)

acronyms = _table(
    "acronyms",
    _id(),
    Column("name", NAME, nullable=False, unique=True),
    Column("description", Text, nullable=False, default=""),
    Column("created_at", UTCDateTime, nullable=False, server_default=_NOW),
    Column(
        "updated_at", UTCDateTime, nullable=False, server_default=_NOW, onupdate=utcnow
    ),
)

conversation_analytics = _table(
    "conversation_analytics",
    _id(),
    Column("user_id", ID, nullable=False),
    Column("source", SHORT, nullable=False, server_default=text("'app'")),
    Column("question", Text, nullable=False, default=""),
    Column("question_timestamp", UTCDateTime, nullable=False, server_default=_NOW),
    Column("response", MEDIUMTEXT, nullable=True),
    Column("response_timestamp", UTCDateTime, nullable=True),
    Column("sql", Text, nullable=True),
)

# Pipeline jobs take a lease before they touch the catalog, so a scheduled run
# and one started from the app never overlap. A lease nobody renews expires.
job_lease = _table(
    "job_lease",
    Column("name", SHORT, primary_key=True),
    Column("holder", String(255), nullable=False),
    Column("expires_at", UTCDateTime, nullable=False),
)

# The source of truth for which migration steps have landed; see
# auto_ontology.dal.migrations.
schema_version = _table(
    "schema_version",
    Column("step", NAME, primary_key=True),
    Column("applied_at", UTCDateTime, nullable=False, server_default=_NOW),
)

# ---------------------------------------------------------------------------
# Indexes for the read paths
# ---------------------------------------------------------------------------

Index(
    "ix_vector_row_collection_database",
    vector_row.c.collection,
    vector_row.c.database_name,
)
Index("ix_conversations_user_id", conversations.c.user_id)
Index(
    "ix_messages_conversation_id_created_at",
    messages.c.conversation_id,
    messages.c.created_at,
)
Index("ix_conversation_analytics_user_id", conversation_analytics.c.user_id)

Index("ix_catalog_schema_database_id", catalog_schema.c.database_id)
Index("ix_catalog_table_schema_id", catalog_table.c.schema_id)
Index("ix_catalog_table_name", catalog_table.c.name)
Index("ix_catalog_column_table_id", catalog_column.c.table_id)
Index("ix_catalog_column_name", catalog_column.c.name)

Index("ix_column__foreign_key_target", column__foreign_key.c.target_column_id)
Index("ix_table__join_target", table__join.c.target_table_id)
Index("ix_sql_query__table_table_id", sql_query__table.c.table_id)
Index("ix_sql_query__column_column_id", sql_query__column.c.column_id)

Index("ix_term_name", term.c.name)
Index("ix_table__term_term_id", table__term.c.term_id)
Index("ix_column_attribute_term_name", column_attribute.c.term_name)
Index("ix_column_attribute_table_id", column_attribute.c.table_id)
Index("ix_column_attribute__term_term_id", column_attribute__term.c.term_id)
Index("ix_sql_attribute__term_term_id", sql_attribute__term.c.term_id)

# Both link tables are read in both directions -- from a column to its
# attributes, and from an attribute back to the columns that reference it
# (`fetch_attr_column_contexts` binds the attribute first). The composite
# primary key already indexes the column_id order; these cover the reverse.
Index("ix_column__has_attribute_attribute_id", column__has_attribute.c.attribute_id)
Index("ix_column__semantic_fk_attribute_id", column__semantic_fk.c.attribute_id)

Index("ix_zone_target_zone_id", zone_target.c.zone_id)
Index("ix_zone_target_database_id", zone_target.c.database_id)
Index("ix_zone_target_schema_id", zone_target.c.schema_id)
Index("ix_zone_target_table_id", zone_target.c.table_id)

# "The groups of this account". The primary key of ``user_group__member`` leads
# with ``group_id`` and so cannot serve it.
Index("ix_user_group__member_user_id", user_group__member.c.user_id)

# "The tags on this object", which every detail page asks for its own kind. The
# unique constraints on tag_target lead with `tag_id` and so cannot serve it.
Index("ix_tag_target_term_id", tag_target.c.term_id)
Index("ix_tag_target_table_id", tag_target.c.table_id)
Index("ix_tag_target_column_id", tag_target.c.column_id)
Index("ix_tag_target_column_attribute_id", tag_target.c.column_attribute_id)
Index("ix_tag_target_sql_attribute_id", tag_target.c.sql_attribute_id)

# The order the Rules settings page renders in, and the reverse read the
# cascade needs: `rule__tag`'s primary key leads with `rule_id`, so deleting a
# tag would scan the whole table for the rules that carry it without this.
Index("ix_rule__tag_tag_id", rule__tag.c.tag_id)

# The other side of that cascade: deleting a rule takes back every label it
# applied, and nothing else leads with `tag_target.rule_id`.
Index("ix_tag_target_rule_id", tag_target.c.rule_id)

# imported_id is matched alongside id during model import; non-unique.
for _imported in (
    catalog_database,
    catalog_schema,
    catalog_table,
    catalog_column,
    term,
    column_attribute,
    sql_attribute,
    custom_analysis,
):
    Index(f"ix_{_imported.name}_imported_id", _imported.c.imported_id)

__all__ = [
    "METADATA",
    "TABLE_PREFIX",
    "acronyms",
    "configurations",
    "conversation_analytics",
    "conversations",
    "job_lease",
    "messages",
    "prompts",
    "schema_version",
    "vector_row",
    "column__join",
    "column__union",
    "analysis",
    "catalog_column",
    "catalog_database",
    "catalog_schema",
    "catalog_table",
    "column_attribute",
    "column__has_attribute",
    "column__semantic_fk",
    "column_attribute__term",
    "column__foreign_key",
    "custom_analysis",
    "custom_analysis__sql",
    "pql_analysis",
    "sql_attribute",
    "sql_attribute__sql",
    "sql_attribute__term",
    "sql_query",
    "sql_query__table",
    "sql_query__column",
    "semantic_compilation_history",
    "table__join",
    "table__term",
    "term",
    "text_attribute",
    "user_group",
    "user_group__member",
    "GroupRole",
    "GROUP_ROLE_ADMIN",
    "GROUP_ROLE_VIEWER",
    "zone",
    "zone_target",
]
