/* Call-site-specific ABI: xmm8 = aspect, xmm9 = authored vertical FOV,
 * r10 = camera. The caller deliberately consumes the adjusted xmm9.
 * Statically linked so Windows has valid unwind metadata before publication.
 */
.intel_syntax noprefix
.text
.global adaptive_camera_entry
.seh_proc adaptive_camera_entry
adaptive_camera_entry:
    sub rsp, 0x48
    .seh_stackalloc 0x48
    movaps [rsp + 0x20], xmm9
    .seh_savexmm xmm9, 0x20
    .seh_endprologue
    mov [rsp + 0x30], r10
    mov rax, qword ptr [rip + adaptive_engine_global]
    test rax, rax
    jz original_inputs
    mov rax, qword ptr [rax]
    test rax, rax
    jz original_inputs
    mov rax, qword ptr [rax + 0x13f0]
    test rax, rax
    jz original_inputs
    mov rax, qword ptr [rax + 0x18]
    test rax, rax
    jz original_inputs
    mov rax, qword ptr [rax + 0x1a80]
    test rax, rax
    jz original_inputs
    cmp qword ptr [rax + 0x30], r10
    jne original_inputs
    movss xmm0, dword ptr [rip + reference_aspect]
    comiss xmm8, xmm0
    jae original_inputs
    jp original_inputs
    xorps xmm1, xmm1
    comiss xmm8, xmm1
    jbe original_inputs
    divss xmm0, xmm8
    movaps xmm1, xmm9
    call qword ptr [rip + adaptive_native_fov]
    movaps xmm9, xmm0
original_inputs:
    movaps xmm0, xmm8
    movaps xmm1, xmm9
    mov r10, qword ptr [rsp + 0x30]
    call qword ptr [rip + adaptive_native_fov]
    mov r10, qword ptr [rsp + 0x30]
    add rsp, 0x48
    ret
.seh_endproc
.section .rdata,"dr"
.balign 4
reference_aspect: .float 1.7777777777777778
