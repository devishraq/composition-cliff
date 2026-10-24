"""
analyze_specification_quality.py

In-memory diagnostic script to analyze the qualitative semantic depth,
quantifier density, and failure mode trade-offs between:
  - Mode 1: Compiler-Only Feedback
  - Mode 2: Mutation-Guided CEGIS

Saves structured analysis directly to: results/specification_quality_analysis.json
"""

import os
import glob
import json
import re

def parse_spec_features(specs_str):
    if not specs_str or not isinstance(specs_str, str):
        return {
            "ensures_lines": 0,
            "requires_lines": 0,
            "quantifiers": 0,
            "equalities": 0,
            "inequalities": 0,
            "implications": 0,
            "total_chars": 0
        }
    
    lines = [l.strip() for l in specs_str.splitlines() if l.strip()]
    ensures = [l for l in lines if l.startswith('ensures')]
    requires = [l for l in lines if l.startswith('requires')]
    
    quantifiers = sum(1 for l in ensures if 'forall' in l or 'exists' in l)
    
    equalities = sum(1 for l in ensures if '==' in l or '<==>' in l)
    inequalities = sum(1 for l in ensures if any(op in l for op in ['>=', '<=', '>', '<', '!=']))
    
    implications = sum(1 for l in ensures if '==>' in l)
    
    return {
        "ensures_lines": len(ensures),
        "requires_lines": len(requires),
        "quantifiers": quantifiers,
        "equalities": equalities,
        "inequalities": inequalities,
        "implications": implications,
        "total_chars": sum(len(l) for l in ensures)
    }

def run_diagnostic_for_track(track_dir="results/dafny_comp"):
    track_name = os.path.basename(track_dir)
    model_dirs = sorted(glob.glob(f"{track_dir}/*"))
    
    macro_complexity = []
    head_to_head = []
    failure_taxonomy = []
    
    model_data = {}
    
    for m_path in model_dirs:
        if not os.path.isdir(m_path):
            continue
        model_slug = os.path.basename(m_path)
        
        m1_file = os.path.join(m_path, "compiler_only.json")
        m2_file = os.path.join(m_path, "mutation_cegis.json")
        
        if not (os.path.exists(m1_file) and os.path.exists(m2_file)):
            continue
            
        try:
            m1_tasks = {t['task_name']: t for t in json.load(open(m1_file)).get('tasks', [])}
            m2_tasks = {t['task_name']: t for t in json.load(open(m2_file)).get('tasks', [])}
        except Exception:
            continue
            
        model_data[model_slug] = (m1_tasks, m2_tasks)
        
        for mode_key, mode_name, tasks_dict in [("compiler_only", "Mode 1 (Comp)", m1_tasks), ("mutation_cegis", "Mode 2 (CEGIS)", m2_tasks)]:
            tot_q = 0
            tot_eq = 0
            tot_ineq = 0
            tot_imp = 0
            
            for t in tasks_dict.values():
                feat = parse_spec_features(t.get('final_specs', ''))
                tot_q += feat['quantifiers']
                tot_eq += feat['equalities']
                tot_ineq += feat['inequalities']
                tot_imp += feat['implications']
                
            macro_complexity.append({
                "model": model_slug,
                "mode_key": mode_key,
                "mode_label": mode_name,
                "quantifiers": tot_q,
                "exact_equalities": tot_eq,
                "loose_inequalities": tot_ineq,
                "implications": tot_imp
            })
            
    for model_slug, (m1_tasks, m2_tasks) in model_data.items():
        common = set(m1_tasks.keys()) & set(m2_tasks.keys())
        
        joint_passed = []
        for name in common:
            t1, t2 = m1_tasks[name], m2_tasks[name]
            if t1.get('task_success', False) and t2.get('task_success', False):
                joint_passed.append((t1.get('final_adj_score', 0.0), t2.get('final_adj_score', 0.0)))
                
        if joint_passed:
            avg_m1 = sum(x[0] for x in joint_passed) / len(joint_passed)
            avg_m2 = sum(x[1] for x in joint_passed) / len(joint_passed)
            delta = avg_m2 - avg_m1
            head_to_head.append({
                "model": model_slug,
                "joint_verified_count": len(joint_passed),
                "m1_mean_s_adj": round(avg_m1, 4),
                "m2_mean_s_adj": round(avg_m2, 4),
                "m2_quality_delta": round(delta, 4)
            })
        else:
            head_to_head.append({
                "model": model_slug,
                "joint_verified_count": 0,
                "m1_mean_s_adj": None,
                "m2_mean_s_adj": None,
                "m2_quality_delta": None
            })
            
    for model_slug, (m1_tasks, m2_tasks) in model_data.items():
        common = set(m1_tasks.keys()) & set(m2_tasks.keys())
        
        m1_only_passes = []
        for name in common:
            t1, t2 = m1_tasks[name], m2_tasks[name]
            if t1.get('task_success', False) and not t2.get('task_success', False):
                len1 = len(t1.get('final_specs', ''))
                len2 = len(t2.get('final_specs', ''))
                m1_only_passes.append((len1, len2))
                
        if m1_only_passes:
            avg_l1 = sum(x[0] for x in m1_only_passes) / len(m1_only_passes)
            avg_l2 = sum(x[1] for x in m1_only_passes) / len(m1_only_passes)
            failure_taxonomy.append({
                "model": model_slug,
                "m1_pass_m2_fail_count": len(m1_only_passes),
                "avg_spec_len_m1_chars": round(avg_l1, 1),
                "avg_spec_len_m2_chars": round(avg_l2, 1)
            })
        else:
            failure_taxonomy.append({
                "model": model_slug,
                "m1_pass_m2_fail_count": 0,
                "avg_spec_len_m1_chars": 0.0,
                "avg_spec_len_m2_chars": 0.0
            })
            
    return {
        "track": track_name,
        "macro_complexity": macro_complexity,
        "head_to_head": head_to_head,
        "failure_taxonomy": failure_taxonomy
    }

def main():
    tracks = []
    for track_dir in ["results/dafny_comp", "results/clover_bench"]:
        if os.path.exists(track_dir):
            res = run_diagnostic_for_track(track_dir)
            tracks.append(res)
            
    out_payload = {
        "description": "Specification quality, quantifier density, and verification game diagnostic",
        "tracks": tracks
    }
    
    os.makedirs("results", exist_ok=True)
    out_path = "results/specification_quality_analysis.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_payload, f, indent=2)
        
    print(f"Successfully generated JSON analysis to: {out_path}")

    for t in tracks:
        print(f"\n==========================================================================================")
        print(f" SPECIFICATION QUALITY & VERIFICATION GAME DIAGNOSTIC ({t['track']})")
        print(f"==========================================================================================\n")
        print(f"{'Model Name':<32} | {'Mode':<15} | {'Quantifiers':<12} | {'Exact (==)':<12} | {'Loose (>=)':<12} | {'Implications':<12}")
        print("-" * 105)
        for row in t['macro_complexity']:
            print(f"{row['model']:<32} | {row['mode_label']:<15} | {row['quantifiers']:<12} | {row['exact_equalities']:<12} | {row['loose_inequalities']:<12} | {row['implications']:<12}")
        print("-" * 105)

if __name__ == "__main__":
    main()
