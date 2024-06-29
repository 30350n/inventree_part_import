{pkgs ? import <nixpkgs> {}}:
pkgs.mkShell {
    nativeBuildInputs = with pkgs.buildPackages; [
        python3
        pre-commit
    ];
}
