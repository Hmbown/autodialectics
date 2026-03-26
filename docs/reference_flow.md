# Autodialectic Reference Flow

This is the reference process map for the full autodialectic system. It is intentionally broader than the current implementation so we can use it as the target shape while tightening each part.

```mermaid
flowchart TD
    subgraph Entry["Entry + Configuration"]
        CLI["CLI / API / Bench Runner"]
        CFG["Settings + Policy Surfaces"]
    end

    subgraph Routing["Model Routing"]
        MC["ModelClient"]
        CP["cliproxy / Hermes / OpenAI-compatible endpoint"]
        DLM["DSPy LM context"]
    end

    subgraph Core["Core Run Pipeline"]
        SUB["TaskSubmission"]
        CC["ContractCompiler"]
        TC["TaskContract"]
        CE["ContextExplorer"]
        HX["Heuristic lexical exploration"]
        RLM["DSPy recursive language-model exploration"]
        EB["EvidenceBundle"]
        DP["DialecticalPlanner"]
        TH["Thesis"]
        AN["Antithesis"]
        SY["Synthesis"]
        AR["AdapterRegistry"]
        EX["ExecutionAdapter by domain"]
        EA["ExecutionArtifact"]
        VF["Independent verification"]
        VR["VerificationReport"]
        EV["RunEvaluator + slop metrics"]
        RE["RunEvaluation"]
        GT["AdvanceGate"]
        RD["Decision: accept / revise / reject / rollback"]
    end

    subgraph Persistence["Persistence + Inspection"]
        FS["ArtifactStore"]
        DB["SqliteStore"]
        SUM["Run summary / inspect / replay"]
    end

    subgraph Evolution["Benchmark + Evolution"]
        BM["Benchmark cases + reports"]
        CCM["ChampionChallengerManager"]
        GEPA["DSPy GEPA prompt evolution"]
        HM["Heuristic challenger mutation"]
        CH["Challenger policy"]
        CMP["Champion vs challenger comparison"]
        PR["Promote / rollback champion"]
    end

    CLI --> CFG
    CLI --> SUB
    CFG --> MC
    CFG --> DLM
    MC --> CP
    DLM --> CP

    SUB --> CC
    CC --> TC
    TC --> CE
    CE --> HX
    CE --> RLM
    HX --> EB
    RLM --> EB
    TC --> DP
    EB --> DP
    DP --> TH
    TH --> AN
    AN --> SY
    SY --> AR
    TC --> AR
    EB --> AR
    AR --> EX
    EX --> EA
    MC --> EX

    TC --> VF
    EB --> VF
    EA --> VF
    VF --> VR

    TC --> EV
    EB --> EV
    SY --> EV
    EA --> EV
    VR --> EV
    EV --> RE
    VR --> GT
    RE --> GT
    GT --> RD

    TC --> FS
    EB --> FS
    SY --> FS
    EA --> FS
    VR --> FS
    RE --> FS
    RD --> FS
    FS --> DB
    DB --> SUM

    RE --> BM
    VR --> BM
    BM --> CCM
    CFG --> CCM
    CCM --> GEPA
    CCM --> HM
    DLM --> GEPA
    GEPA --> CH
    HM --> CH
    CH --> CMP
    BM --> CMP
    CMP --> PR
    PR --> DB
```

Implementation notes
- `ModelClient` and DSPy should route through the same configured OpenAI-compatible endpoint unless explicitly separated.
- DSPy RLM is the long-context recursive exploration branch, not a plain retrieval pass.
- Dialectics must preserve the full thesis -> antithesis -> synthesis handoff because downstream evaluation depends on objection coverage.
- Verification and evaluation stay independent from execution.
- Champion/challenger evolution only promotes after benchmark comparison and canary protection.
